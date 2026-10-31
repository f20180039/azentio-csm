"""Port of RenewalServiceTest and RenewalHttpTest: verification, playbook guard rails, outcomes, summary."""
import uuid

import pytest

from conftest import ANALYST, MEERA, MEERA_DOB, VOICE, actions, audit, start_call, verified_call

ARJUN_COMPLAINT = "MC-3380-1126"
SNEHA_DNC = "TL-3281-8107"
BASE = "/api/v1/renewals/calls"


def post(client, cid, tail, body=None, who=VOICE):
    return client.post(f"{BASE}/{cid}/{tail}", json=body or {}, headers=who)


def get(client, cid, tail="", who=VOICE):
    return client.get(f"{BASE}/{cid}{('/' + tail) if tail else ''}", headers=who)


def quote(client, cid, drop=(), plan="annual", discount=0):
    return post(client, cid, "quote", {"dropAddons": list(drop), "paymentPlan": plan, "discountPercent": discount})


def assert_refused(resp, status, code):
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["detail"] == code


def refused_with(client, cid, code):
    return any(e["action"] == "tool.refused" and e["payload"].get("code") == code for e in audit(client, cid))


def call_row(client, cid):
    with client.services.db.read() as con:
        return dict(con.execute("SELECT * FROM calls WHERE id = ?", (cid,)).fetchone())


def add_base_addon(client):
    with client.services.db.tx() as con:
        con.execute("UPDATE policies SET addons = ? WHERE id = ?", (
            '[{"code":"OPD","name":"Outpatient cover","premium":2100,"optional":true},'
            '{"code":"BASE","name":"Base cover","premium":9000,"optional":false}]', MEERA))


# ---- queue and starting calls ----

def test_queue_is_sorted_excludes_expired_and_routes(make_client):
    client = make_client("2026-10-31T11:00:00")
    q = client.get("/api/v1/renewals/queue", headers=ANALYST).json()
    assert isinstance(q, list)
    assert all(item["daysToExpiry"] >= 0 for item in q)
    assert "TL-6140-6572" not in [i["policyId"] for i in q]  # expired 2026-10-30
    keys = [(-i["score"], i["daysToExpiry"]) for i in q]
    assert keys == sorted(keys)
    meera = next(i for i in q if i["policyId"] == MEERA)
    assert meera["daysToExpiry"] == 3
    assert meera["route"] == "AGENT_CALL"
    assert [s["code"] for s in meera["signals"]] == ["EXPIRY_7D", "PREMIUM_UP_15", "REMINDERS_IGNORED"]
    assert set(meera) == {"policyId", "holderName", "product", "expiresOn", "daysToExpiry", "score", "signals", "route"}
    assert next(i for i in q if i["policyId"] == ARJUN_COMPLAINT)["route"] == "HUMAN_ONLY"


def test_human_only_and_do_not_call_policies_cannot_be_called(client):
    for pid, code in ((ARJUN_COMPLAINT, "HUMAN_ONLY"), (SNEHA_DNC, "DO_NOT_CALL")):
        r = client.post(BASE, json={"policyId": pid}, headers=ANALYST)
        assert_refused(r, 409, code)
    with client.services.db.read() as con:
        assert con.execute("SELECT count(*) FROM cases").fetchone()[0] == 0


@pytest.mark.parametrize("when,enforce,allowed", [
    ("2026-10-29T21:30:00", True, False),
    ("2026-10-29T08:59:00", True, False),
    ("2026-10-29T21:30:00", False, True),
    ("2026-10-29T09:00:00", True, True),
])
def test_calling_hours(make_client, when, enforce, allowed):
    c = make_client(when, enforce)
    r = c.post(BASE, json={"policyId": MEERA}, headers=ANALYST)
    if allowed:
        assert r.status_code == 201
    else:
        assert_refused(r, 409, "OUTSIDE_CALLING_HOURS")


def test_enforce_calling_hours_defaults_true(monkeypatch):
    from app.config import Settings
    monkeypatch.delenv("ENFORCE_CALLING_HOURS", raising=False)
    assert Settings.from_env().enforce_calling_hours is True
    monkeypatch.setenv("ENFORCE_CALLING_HOURS", "false")
    assert Settings.from_env().enforce_calling_hours is False


def test_unknown_policy_is_404_and_missing_policy_is_400(client):
    assert client.post(BASE, json={"policyId": "x"}, headers=ANALYST).status_code == 404
    assert client.post(BASE, json={}, headers=ANALYST).status_code == 400


def test_start_call_creates_case_call_row_and_audit(client):
    r = client.post(BASE, json={"policyId": MEERA}, headers=ANALYST).json()
    assert r["callId"] == r["caseId"]
    assert r["greeting"] == ("Hello, this call is recorded. I'm the renewals assistant from "
                             "Lotusleaf General Insurance. Am I speaking with Meera Iyer?")
    case = client.get(f"/api/v1/cases/{r['callId']}", headers=ANALYST).json()
    assert case["caseType"] == "renewal_call"
    assert case["title"] == "Renewal call · Meera Iyer"
    assert case["status"] == "PROCESSING"
    assert case["attributes"] == {"policyId": MEERA}
    assert call_row(client, r["callId"])["policy_id"] == MEERA
    first = audit(client, r["callId"])[0]
    assert first["action"] == "call.started" and first["actor"] == "analyst"


def test_simulated_call_is_tagged(client):
    cid = start_call(client, simulated=True)
    attrs = client.get(f"/api/v1/cases/{cid}", headers=ANALYST).json()["attributes"]
    assert attrs == {"policyId": MEERA, "simulated": True}


# ---- verification ----

def test_policy_before_verify_is_refused(client):
    cid = start_call(client)
    assert_refused(get(client, cid, "policy"), 403, "IDENTITY_NOT_VERIFIED")
    assert_refused(get(client, cid, "options"), 403, "IDENTITY_NOT_VERIFIED")
    assert_refused(quote(client, cid), 403, "IDENTITY_NOT_VERIFIED")
    assert_refused(post(client, cid, "payment-link", {"quoteId": str(uuid.uuid4())}), 403, "IDENTITY_NOT_VERIFIED")
    assert "tool.get_policy" not in actions(client, cid)
    last = audit(client, cid)[-1]
    assert last["action"] == "tool.refused" and last["payload"]["tool"] == "send_payment_link"


def test_policy_after_verify_shows_renewal_detail(client):
    cid = verified_call(client)
    v = get(client, cid, "policy").json()
    assert v["policyId"] == MEERA
    assert v["renewalPremium"] == 18450 and v["lastPremium"] == 15120
    assert v["mobileLast4"] == "4821" and v["sumInsured"] == 1000000
    assert len(v["breakdown"]) == 2 and v["mustHandoff"] is False
    o = get(client, cid, "options").json()
    assert o["removableAddons"] == [{"code": "OPD", "name": "Outpatient cover", "saving": 2100}]
    assert o["paymentPlans"] == ["annual", "quarterly"]
    assert o["maxDiscountPercent"] == 0
    acts = actions(client, cid)
    assert acts.index("call.started") < acts.index("identity.verified") < acts.index("tool.get_policy")
    assert "tool.list_allowed_options" in acts


def test_wrong_dob_counts_down_then_right_dob_verifies(client):
    cid = start_call(client)
    a = post(client, cid, "verify", {"dateOfBirth": "1980-03-15"}).json()
    assert a == {"verified": False, "attemptsLeft": 2, "mustHandoff": False}
    assert post(client, cid, "verify", {"dateOfBirth": "1999-01-01"}).json()["attemptsLeft"] == 1
    assert "identity.failed" in actions(client, cid) and "identity.verified" not in actions(client, cid)
    assert post(client, cid, "verify", {"dateOfBirth": MEERA_DOB}).json()["verified"] is True


def test_third_failed_verify_locks_and_forces_handoff(client):
    cid = start_call(client)
    post(client, cid, "verify", {"dateOfBirth": "1980-03-15"})
    post(client, cid, "verify", {"dateOfBirth": "1980-03-16"})
    last = post(client, cid, "verify", {"dateOfBirth": "1980-03-17"}).json()
    assert last["attemptsLeft"] == 0 and last["mustHandoff"] is True
    assert_refused(post(client, cid, "verify", {"dateOfBirth": MEERA_DOB}), 409, "VERIFY_LOCKED")
    assert_refused(get(client, cid, "policy"), 403, "IDENTITY_NOT_VERIFIED")
    assert refused_with(client, cid, "VERIFY_LOCKED")


def test_malformed_dob_is_400_and_not_counted(client):
    cid = start_call(client)
    for bad in ("14/03/1980", "19800314", None):
        assert post(client, cid, "verify", {"dateOfBirth": bad}).status_code == 400
    assert call_row(client, cid)["verify_failures"] == 0


def test_already_verified_is_audited(client):
    cid = verified_call(client)
    assert post(client, cid, "verify", {"dateOfBirth": MEERA_DOB}).json()["verified"] is True
    assert refused_with(client, cid, "ALREADY_VERIFIED")


# ---- quotes and playbook limits ----

def test_quote_drops_opd_quarterly(client):
    cid = verified_call(client)
    q = quote(client, cid, ["OPD"], "quarterly").json()
    assert (q["annualPremium"], q["instalments"], q["perInstalment"]) == (16350, 4, 4088)
    assert q["quoteId"] in call_row(client, cid)["last_quote"]
    annual = quote(client, cid).json()
    assert (annual["annualPremium"], annual["instalments"], annual["perInstalment"]) == (18450, 1, 18450)
    assert "tool.quote_renewal" in actions(client, cid)


def test_non_optional_unknown_addon_and_unknown_plan_are_invalid(client):
    add_base_addon(client)
    cid = verified_call(client)
    assert_refused(quote(client, cid, ["BASE"]), 422, "INVALID_OPTION")
    assert_refused(quote(client, cid, ["NOPE"]), 422, "INVALID_OPTION")
    assert_refused(quote(client, cid, plan="monthly"), 422, "INVALID_OPTION")
    assert_refused(quote(client, cid, discount=-5), 422, "INVALID_OPTION")
    row = call_row(client, cid)
    assert row["last_quote"] is None and row["out_of_playbook_requests"] == 0
    assert refused_with(client, cid, "INVALID_OPTION")


def test_discount_is_checked_before_options(client):
    cid = verified_call(client)
    assert_refused(quote(client, cid, plan="", discount=1), 422, "OUTSIDE_PLAYBOOK")
    assert call_row(client, cid)["out_of_playbook_requests"] == 1
    assert "rule.outside_playbook" in actions(client, cid)


def test_over_limit_discount_is_never_applied_and_second_forces_handoff(client):
    cid = verified_call(client)
    assert_refused(quote(client, cid, discount=10), 422, "OUTSIDE_PLAYBOOK")
    row = call_row(client, cid)
    assert row["out_of_playbook_requests"] == 1 and row["must_handoff"] == 0 and row["last_quote"] is None
    assert_refused(quote(client, cid, discount=5), 422, "OUTSIDE_PLAYBOOK")
    row = call_row(client, cid)
    assert row["out_of_playbook_requests"] == 2 and row["must_handoff"] == 1 and row["last_quote"] is None
    assert actions(client, cid).count("rule.outside_playbook") == 2
    ev = next(e for e in audit(client, cid) if e["action"] == "rule.outside_playbook")
    assert ev["payload"]["requestedDiscountPercent"] == 10 and ev["payload"]["maxDiscountPercent"] == 0


def test_quote_and_options_refused_after_forced_handoff_then_handoff_and_end(client):
    cid = verified_call(client)
    for _ in range(2):
        assert_refused(quote(client, cid, discount=10), 422, "OUTSIDE_PLAYBOOK")
    assert_refused(quote(client, cid), 409, "MUST_HANDOFF")
    assert_refused(get(client, cid, "options"), 409, "MUST_HANDOFF")
    assert refused_with(client, cid, "MUST_HANDOFF")
    assert post(client, cid, "turns", {"role": "customer", "text": "ok", "at": "t"}).status_code == 204
    assert post(client, cid, "handoff", {"reason": "limit reached"}).json() == {"queued": True, "mustHandoff": True}
    assert post(client, cid, "end").json()["outcome"] == "HANDED_OFF"
    assert get(client, cid).json()["mustHandoff"] is True


def test_payment_link_refused_after_forced_handoff(client):
    cid = verified_call(client)
    q = quote(client, cid).json()
    for _ in range(2):
        quote(client, cid, discount=10)
    assert_refused(post(client, cid, "payment-link", {"quoteId": q["quoteId"]}), 409, "MUST_HANDOFF")
    assert call_row(client, cid)["payment_link_sent"] == 0


def test_quote_after_voluntary_handoff_is_refused(client):
    cid = verified_call(client)
    post(client, cid, "handoff", {"reason": "Customer wants a person"})
    assert_refused(quote(client, cid), 409, "MUST_HANDOFF")
    assert_refused(post(client, cid, "payment-link", {"quoteId": str(uuid.uuid4())}), 409, "MUST_HANDOFF")


def test_payment_link_needs_latest_quote_of_this_call(client):
    cid = verified_call(client)
    first = quote(client, cid, ["OPD"], "quarterly").json()
    second = quote(client, cid).json()
    assert_refused(post(client, cid, "payment-link", {"quoteId": first["quoteId"]}), 409, "STALE_QUOTE")
    other = verified_call(client)
    other_quote = quote(client, other).json()
    assert_refused(post(client, cid, "payment-link", {"quoteId": other_quote["quoteId"]}), 409, "STALE_QUOTE")
    assert call_row(client, cid)["payment_link_sent"] == 0
    sent = post(client, cid, "payment-link", {"quoteId": second["quoteId"]}).json()
    assert sent == {"sent": True, "channel": "SMS", "mobileLast4": "4821", "mustHandoff": False}
    assert "tool.send_payment_link" in actions(client, cid)
    assert refused_with(client, cid, "STALE_QUOTE")


def test_handoff_needs_a_reason(client):
    cid = start_call(client)
    assert post(client, cid, "handoff", {"reason": " "}).status_code == 400


# ---- ending and the call view ----

def test_end_outcomes_and_case_status(client):
    paid = verified_call(client)
    post(client, paid, "payment-link", {"quoteId": quote(client, paid).json()["quoteId"]})
    assert post(client, paid, "end").json()["outcome"] == "RENEWAL_PENDING_PAYMENT"
    assert client.get(f"/api/v1/cases/{paid}", headers=ANALYST).json()["status"] == "NEEDS_REVIEW"
    assert call_row(client, paid)["ended_at"] is not None

    none = start_call(client)
    assert post(client, none, "end").json()["outcome"] == "NO_DECISION"

    handed = start_call(client)
    post(client, handed, "handoff", {"reason": "Customer wants a manager", "callbackAt": "2026-10-30T10:00:00+05:30"})
    assert client.get(f"/api/v1/cases/{handed}", headers=ANALYST).json()["status"] == "ESCALATED"
    assert post(client, handed, "end").json()["outcome"] == "HANDED_OFF"
    assert post(client, handed, "end", who=ANALYST).json()["outcome"] == "HANDED_OFF"
    assert client.get(f"/api/v1/cases/{handed}", headers=ANALYST).json()["status"] == "ESCALATED"
    assert actions(client, handed).count("call.ended") == 1


def test_tools_after_end_are_refused(client):
    cid = verified_call(client)
    post(client, cid, "end")
    assert_refused(get(client, cid, "policy"), 409, "CALL_ENDED")
    assert_refused(post(client, cid, "verify", {"dateOfBirth": MEERA_DOB}), 409, "CALL_ENDED")
    assert_refused(quote(client, cid), 409, "CALL_ENDED")
    assert_refused(post(client, cid, "handoff", {"reason": "x"}), 409, "CALL_ENDED")
    assert_refused(post(client, cid, "turns", {"role": "agent", "text": "hi", "at": "t"}), 409, "CALL_ENDED")
    assert refused_with(client, cid, "CALL_ENDED")


def test_summary_quotes_preceding_customer_turn(client):
    cid = verified_call(client)

    def turn(role, text):
        assert post(client, cid, "turns", {"role": role, "text": text, "at": "t"}).status_code == 204

    turn("agent", "Your premium is 18450.")
    turn("customer", "Can you give me a discount?")
    turn("agent", "Let me check.")
    assert_refused(quote(client, cid, discount=10), 422, "OUTSIDE_PLAYBOOK")
    turn("customer", "Drop the outpatient cover, pay quarterly.")
    q = quote(client, cid, ["OPD"], "quarterly").json()
    turn("customer", "Send me the link.")
    post(client, cid, "payment-link", {"quoteId": q["quoteId"]})
    v = get(client, cid, who=ANALYST).json()
    assert [s["statement"] for s in v["summary"]] == [
        "Customer asked for a discount beyond the playbook limit.",
        "Agent quoted a renewal option within the playbook.",
        "Payment link sent to the customer's registered mobile."]
    assert [s["quote"] for s in v["summary"]] == [
        "Can you give me a discount?", "Drop the outpatient cover, pay quarterly.", "Send me the link."]
    assert len(v["transcript"]) == 5
    assert v["holderName"] == "Meera Iyer" and "{holderName}" not in v["greeting"]
    assert v["identityVerified"] and v["paymentLinkSent"] and v["outOfPlaybookRequests"] == 1
    assert v["lastQuote"]["annualPremium"] == 16350
    assert set(v) >= {"callId", "caseId", "policyId", "verifyFailures", "mustHandoff", "outcome", "handoffReason",
                      "callbackAt"}


def test_turn_rejects_bad_role_and_empty_text(client):
    cid = start_call(client)
    assert post(client, cid, "turns", {"role": "robot", "text": "hi"}).status_code == 400
    assert post(client, cid, "turns", {"role": "agent", "text": " "}).status_code == 400


# ---- HTTP contract ----

def test_unknown_call_is_404_and_bad_uuid_is_400(client):
    assert get(client, uuid.uuid4(), who=ANALYST).status_code == 404
    assert get(client, uuid.uuid4()).status_code == 404
    assert get(client, uuid.uuid4()).headers["content-type"].startswith("application/problem+json")
    assert client.get(f"{BASE}/not-a-uuid", headers=ANALYST).status_code == 400
    assert client.get(f"{BASE}/{uuid.uuid4()}").status_code == 401


def test_validation_errors_are_400_with_string_detail(client):
    cid = verified_call(client)
    r = post(client, cid, "quote", {"discountPercent": "lots"})
    assert r.status_code == 400 and isinstance(r.json()["detail"], str)
