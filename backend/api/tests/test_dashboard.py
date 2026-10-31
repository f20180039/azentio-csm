"""Port of DashboardServiceTest: every number comes from stored calls, policies and audit events."""
from conftest import ADMIN, ANALYST, MEERA, VOICE, start_call, verified_call

ZOYA = "HF-7955-1968"
KPI_KEYS = {"callsToday", "callsTotal", "inProgress", "renewed", "handedOff", "noDecision", "premiumRetained",
            "premiumAtRisk", "blockedRequests", "refusals", "identityFailures", "saveRate"}


def dash(client, include_simulated=False):
    params = {"includeSimulated": "true"} if include_simulated else {}
    r = client.get("/api/v1/renewals/dashboard", params=params, headers=ANALYST)
    assert r.status_code == 200
    return r.json()


def renew(client, policy=MEERA, simulated=False, dob="1980-03-14"):
    cid = start_call(client, policy, simulated)
    client.post(f"/api/v1/renewals/calls/{cid}/verify", json={"dateOfBirth": dob}, headers=VOICE)
    q = client.post(f"/api/v1/renewals/calls/{cid}/quote", json={"paymentPlan": "annual"}, headers=VOICE).json()
    client.post(f"/api/v1/renewals/calls/{cid}/payment-link", json={"quoteId": q["quoteId"]}, headers=VOICE)
    client.post(f"/api/v1/renewals/calls/{cid}/end", headers=VOICE)
    return cid


def test_empty_database_gives_zeros_but_policy_risk_is_computed(client):
    d = dash(client)
    assert set(d) == {"kpis", "outcomesByDay", "recentCalls", "guardrailEvents", "riskBands"}
    k = d["kpis"]
    assert set(k) == KPI_KEYS
    assert {key: v for key, v in k.items() if key != "premiumAtRisk"} == {key: 0 for key in KPI_KEYS - {"premiumAtRisk"}}
    assert d["recentCalls"] == [] and d["guardrailEvents"] == []
    assert len(d["outcomesByDay"]) == 7 and d["outcomesByDay"][-1]["day"] == "2026-10-29"
    assert [b["band"] for b in d["riskBands"]] == ["0.0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1.0"]
    with client.services.db.read() as con:
        live = con.execute("SELECT count(*) FROM policies WHERE expires_on >= '2026-10-29'").fetchone()[0]
    assert sum(b["count"] for b in d["riskBands"]) == live
    assert k["premiumAtRisk"] > 0


def test_in_progress_is_not_an_outcome(client):
    start_call(client)
    d = dash(client)
    k = d["kpis"]
    assert (k["callsTotal"], k["callsToday"], k["inProgress"]) == (1, 1, 1)
    assert k["renewed"] + k["handedOff"] + k["noDecision"] == 0 and k["saveRate"] == 0
    assert d["recentCalls"][0]["outcome"] is None and d["recentCalls"][0]["holderName"] == "Meera Iyer"


def test_premium_retained_sums_renewed_quotes_and_save_rate(client):
    renew(client)
    renew(client, ZOYA, dob="1974-11-21")
    handed = start_call(client)
    client.post(f"/api/v1/renewals/calls/{handed}/handoff", json={"reason": "x"}, headers=VOICE)
    client.post(f"/api/v1/renewals/calls/{handed}/end", headers=VOICE)
    none = start_call(client)
    client.post(f"/api/v1/renewals/calls/{none}/end", headers=VOICE)
    k = dash(client)["kpis"]
    assert k["premiumRetained"] == 18450 + 33442
    assert (k["renewed"], k["handedOff"], k["noDecision"]) == (2, 1, 1)
    assert k["saveRate"] == 0.5
    today = dash(client)["outcomesByDay"][-1]
    assert today == {"day": "2026-10-29", "renewed": 2, "handedOff": 1, "noDecision": 1}


def test_outcomes_by_day_zero_fill_seven_days(client):
    client.clock.set("2026-10-23T10:00:00")
    none = start_call(client)
    client.post(f"/api/v1/renewals/calls/{none}/end", headers=VOICE)
    client.clock.set("2026-10-29T11:00:00")
    days = dash(client)["outcomesByDay"]
    assert [d["day"] for d in days] == [f"2026-10-{n}" for n in range(23, 30)]
    assert days[0] == {"day": "2026-10-23", "renewed": 0, "handedOff": 0, "noDecision": 1}
    assert dash(client)["kpis"]["callsToday"] == 0


def test_guardrail_events_newest_first_with_details(client):
    cid = start_call(client)
    client.post(f"/api/v1/renewals/calls/{cid}/verify", json={"dateOfBirth": "1999-01-01"}, headers=VOICE)
    client.post(f"/api/v1/renewals/calls/{cid}/verify", json={"dateOfBirth": "1980-03-14"}, headers=VOICE)
    client.clock.set("2026-10-29T11:01:00")
    client.post(f"/api/v1/renewals/calls/{cid}/quote", json={"paymentPlan": "annual", "discountPercent": 10},
                headers=VOICE)
    client.clock.set("2026-10-29T11:02:00")
    client.post(f"/api/v1/renewals/calls/{cid}/payment-link", json={"quoteId": None}, headers=VOICE)
    d = dash(client)
    assert [e["action"] for e in d["guardrailEvents"]] == ["tool.refused", "rule.outside_playbook", "identity.failed"]
    assert [e["detail"] for e in d["guardrailEvents"]] == ["STALE_QUOTE", "Asked for 10% discount, limit 0%",
                                                           "Attempt 1"]
    assert d["guardrailEvents"][0]["callId"] == cid and d["guardrailEvents"][0]["holderName"] == "Meera Iyer"
    k = d["kpis"]
    assert (k["blockedRequests"], k["refusals"], k["identityFailures"]) == (1, 1, 1)


def test_simulated_calls_left_out_unless_asked_for(client):
    real = renew(client)
    renew(client, ZOYA, simulated=True, dob="1974-11-21")
    real_only = dash(client)
    assert real_only["kpis"]["callsTotal"] == 1 and real_only["kpis"]["premiumRetained"] == 18450
    assert [c["callId"] for c in real_only["recentCalls"]] == [real]
    every = dash(client, include_simulated=True)
    assert every["kpis"]["callsTotal"] == 2 and every["kpis"]["premiumRetained"] == 18450 + 33442
    assert len(every["recentCalls"]) == 2


def test_mark_simulated_moves_a_call_out_of_the_real_stats(client):
    a = renew(client)
    assert client.post("/api/v1/renewals/calls/mark-simulated", json={"callIds": [a]}, headers=ADMIN).json() == \
        {"marked": 1}
    assert dash(client)["kpis"]["callsTotal"] == 0
    attrs = client.get(f"/api/v1/cases/{a}", headers=ANALYST).json()["attributes"]
    assert attrs == {"policyId": MEERA, "simulated": True}


def test_support_calls_never_count_in_renewal_stats(client):
    sid = client.post("/api/v1/support/calls", json={"channel": "VOICE"}, headers=VOICE).json()["id"]
    client.post(f"/api/v1/support/calls/{sid}/end", json={"outcome": "ESCALATED"}, headers=VOICE)
    handed = verified_call(client)
    client.post(f"/api/v1/renewals/calls/{handed}/handoff", json={"reason": "x"}, headers=VOICE)
    client.post(f"/api/v1/renewals/calls/{handed}/end", headers=VOICE)
    d = dash(client)
    assert d["kpis"]["callsTotal"] == 1 and d["kpis"]["handedOff"] == 1
    assert [c["callId"] for c in d["recentCalls"]] == [handed]


def test_stats_are_computed_from_stored_cases(client):
    s = client.get("/api/v1/stats", headers=ANALYST).json()
    assert s == {"byStatus": {}, "renewalCalls": 0, "supportCalls": 0}
    renew(client)
    start_call(client, ZOYA, simulated=True)
    client.post("/api/v1/support/calls", json={"channel": "TEXT"}, headers=VOICE)
    s = client.get("/api/v1/stats", headers=ANALYST).json()
    assert s == {"byStatus": {"NEEDS_REVIEW": 1, "PROCESSING": 1}, "renewalCalls": 1, "supportCalls": 1}
    s = client.get("/api/v1/stats", params={"includeSimulated": "true"}, headers=ANALYST).json()
    assert s["byStatus"] == {"NEEDS_REVIEW": 1, "PROCESSING": 2} and s["renewalCalls"] == 2


def test_cases_list_is_a_spring_page(client):
    start_call(client)
    page = client.get("/api/v1/cases", headers=ANALYST).json()
    assert page["totalElements"] == 1 and page["content"][0]["caseType"] == "renewal_call"
    assert client.get("/api/v1/cases", params={"status": "NOPE"}, headers=ANALYST).status_code == 400
