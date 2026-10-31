"""Who may call what, per SecurityConfig.java and the services' role checks."""
import uuid

import pytest

from conftest import ADMIN, ANALYST, MEERA, REVIEWER, VOICE, start_call, verified_call

ALL_STAFF = [ANALYST, REVIEWER, ADMIN]


def test_me_lists_roles_and_voice_holds_only_voice(client):
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/me", headers=VOICE).json() == {"username": "voice", "roles": ["VOICE"]}
    assert client.get("/api/v1/me", headers=ADMIN).json()["roles"] == ["ADMIN", "ANALYST", "REVIEWER"]
    r = client.get("/api/v1/me", headers={"Authorization": "Basic YW5hbHlzdDp3cm9uZw=="})
    assert r.status_code == 401 and "www-authenticate" not in r.headers


def test_only_voice_writes_support_calls(client):
    for who in ALL_STAFF:
        assert client.post("/api/v1/support/calls", json={"channel": "VOICE"}, headers=who).status_code == 403
    cid = client.post("/api/v1/support/calls", json={"channel": "VOICE"}, headers=VOICE).json()["id"]
    for who in ALL_STAFF:
        assert client.post(f"/api/v1/support/calls/{cid}/turns", json={"role": "agent", "text": "x"},
                           headers=who).status_code == 403
        assert client.patch(f"/api/v1/support/calls/{cid}/turns/1/meta", json={}, headers=who).status_code == 403
        assert client.get(f"/api/v1/support/calls/{cid}", headers=who).status_code == 200
        assert client.get("/api/v1/support/calls", headers=who).status_code == 200
    assert client.get("/api/v1/support/calls").status_code == 401


def test_staff_and_voice_can_end_support_calls(client):
    for who in ALL_STAFF:
        cid = client.post("/api/v1/support/calls", json={"channel": "VOICE"}, headers=VOICE).json()["id"]
        assert client.post(f"/api/v1/support/calls/{cid}/end", json={"outcome": "RESOLVED"}, headers=who).status_code == 200


@pytest.mark.parametrize("method,tail,body", [
    ("post", "verify", {"dateOfBirth": "1980-03-14"}),
    ("get", "policy", None),
    ("get", "options", None),
    ("post", "quote", {"paymentPlan": "annual"}),
    ("post", "payment-link", {"quoteId": str(uuid.uuid4())}),
    ("post", "handoff", {"reason": "x"}),
    ("post", "turns", {"role": "agent", "text": "x"}),
])
def test_only_voice_runs_renewal_call_tools(client, method, tail, body):
    cid = verified_call(client)
    for who in ALL_STAFF:
        kwargs = {"headers": who} if body is None else {"headers": who, "json": body}
        r = getattr(client, method)(f"/api/v1/renewals/calls/{cid}/{tail}", **kwargs)
        assert r.status_code == 403, (who, tail)


def test_staff_start_and_read_renewal_calls_voice_does_not(client):
    assert client.get("/api/v1/renewals/queue", headers=VOICE).status_code == 403
    assert client.post("/api/v1/renewals/calls", json={"policyId": MEERA}, headers=VOICE).status_code == 403
    assert client.get("/api/v1/renewals/dashboard", headers=VOICE).status_code == 403
    assert client.get("/api/v1/renewals/dashboard").status_code == 401
    cid = start_call(client)
    for who in ALL_STAFF + [VOICE]:
        assert client.get(f"/api/v1/renewals/calls/{cid}", headers=who).status_code == 200
    # The web app's End button and the evaluator end calls as staff; the voice agent ends on disconnect.
    assert client.post(f"/api/v1/renewals/calls/{cid}/end", headers=ANALYST).status_code == 200


def test_mark_simulated_is_admin_only(client):
    cid = start_call(client)
    body = {"callIds": [cid]}
    for who in (ANALYST, REVIEWER, VOICE):
        assert client.post("/api/v1/renewals/calls/mark-simulated", json=body, headers=who).status_code == 403
    r = client.post("/api/v1/renewals/calls/mark-simulated", json=body, headers=ADMIN)
    assert r.json() == {"marked": 1}
    assert client.post("/api/v1/renewals/calls/mark-simulated", json={"callIds": []},
                       headers=ADMIN).status_code == 400


def test_audit_verify_is_admin_only(client):
    for who in (ANALYST, REVIEWER, VOICE):
        assert client.get("/api/v1/audit/verify", headers=who).status_code == 403
    assert client.get("/api/v1/audit/verify", headers=ADMIN).status_code == 200


def test_staff_read_cases_packs_stats_voice_does_not(client):
    for path in ("/api/v1/cases", "/api/v1/packs", "/api/v1/stats"):
        assert client.get(path, headers=ANALYST).status_code == 200
        assert client.get(path, headers=VOICE).status_code == 403


def test_only_reviewers_decide_cases_and_never_their_own(client):
    cid = start_call(client)  # created by analyst
    client.post(f"/api/v1/renewals/calls/{cid}/end", headers=VOICE)
    body = {"action": "APPROVE", "reason": "Customer renewed"}
    assert client.post(f"/api/v1/cases/{cid}/decision", json=body, headers=ANALYST).status_code == 403
    assert client.post(f"/api/v1/cases/{cid}/decision", json=body, headers=VOICE).status_code == 403
    r = client.post(f"/api/v1/cases/{cid}/decision", json=body, headers=REVIEWER)
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    mine = client.post("/api/v1/renewals/calls", json={"policyId": MEERA}, headers=REVIEWER).json()["callId"]
    client.post(f"/api/v1/renewals/calls/{mine}/end", headers=VOICE)
    assert client.post(f"/api/v1/cases/{mine}/decision", json=body, headers=REVIEWER).status_code == 403
