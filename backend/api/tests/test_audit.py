"""Port of AuditChainTest, plus the stored chain, /audit/verify and case decisions."""
import sqlite3

import pytest

from conftest import ADMIN, REVIEWER, VOICE, actions, audit, start_call, verified_call
from app.audit import GENESIS, AuditRow, compute_hash, verify_chain


def chain(*acts):
    rows, prev = [], GENESIS
    for i, action in enumerate(acts, start=1):
        payload = {"b": 2, "a": 1.50}
        at = f"2026-10-29T10:00:0{i}.123456Z"
        h = compute_hash(prev, "reviewer", action, payload, at)
        rows.append(AuditRow(i, "case", "reviewer", action, payload, prev, h, at))
        prev = h
    return rows


def test_intact_chain_verifies():
    v = verify_chain(chain("CASE_CREATED", "ROUTED", "CASE_APPROVE"))
    assert v == {"valid": True, "checked": 3, "brokenAt": None, "detail": "All 3 events verified"}


def test_edited_payload_is_detected_at_that_event():
    rows = chain("CASE_CREATED", "ROUTED", "CASE_APPROVE")
    rows[1].payload = {"a": 1.5, "b": 3}
    v = verify_chain(rows)
    assert v["valid"] is False and v["brokenAt"] == 2 and v["checked"] == 1


def test_deleted_event_breaks_the_next_link():
    rows = chain("CASE_CREATED", "ROUTED", "CASE_APPROVE")
    del rows[1]
    v = verify_chain(rows)
    assert v["valid"] is False and v["brokenAt"] == 3


def test_hash_ignores_key_order_and_number_spelling():
    at = "2026-10-29T10:00:00Z"
    h1 = compute_hash(GENESIS, "u", "A", {"x": 1.50, "y": {"q": 1, "p": 2}}, at)
    h2 = compute_hash(GENESIS, "u", "A", {"y": {"p": 2, "q": 1}, "x": 1.5}, at)
    assert h1 == h2 and len(h1) == 64


def test_hash_changes_with_actor():
    at = "2026-10-29T10:00:00Z"
    assert compute_hash(GENESIS, "a", "X", {}, at) != compute_hash(GENESIS, "b", "X", {}, at)


def test_call_lifecycle_is_audited_and_chain_verifies(client):
    cid = start_call(client)
    client.post(f"/api/v1/renewals/calls/{cid}/verify", json={"dateOfBirth": "1999-01-01"}, headers=VOICE)
    client.post(f"/api/v1/renewals/calls/{cid}/verify", json={"dateOfBirth": "1980-03-14"}, headers=VOICE)
    q = client.post(f"/api/v1/renewals/calls/{cid}/quote", json={"paymentPlan": "annual"}, headers=VOICE).json()
    client.post(f"/api/v1/renewals/calls/{cid}/handoff", json={"reason": "wants a person"}, headers=VOICE)
    client.post(f"/api/v1/renewals/calls/{cid}/end", headers=VOICE)
    client.post(f"/api/v1/cases/{cid}/decision", json={"action": "ESCALATE", "reason": "x"}, headers=REVIEWER)
    client.post(f"/api/v1/cases/{cid}/decision", json={"action": "APPROVE", "reason": "callback done"},
                headers=REVIEWER)
    assert actions(client, cid) == ["call.started", "identity.failed", "identity.verified", "tool.quote_renewal",
                                    "tool.handoff_to_human", "call.ended", "CASE_APPROVE"]
    events = audit(client, cid)
    assert events[3]["payload"]["quoteId"] == q["quoteId"]
    assert events[5]["payload"] == {"outcome": "HANDED_OFF"}
    assert events[6]["payload"] == {"from": "ESCALATED", "to": "APPROVED", "reason": "callback done"}
    assert events[1]["prevHash"] == events[0]["hash"]
    v = client.get("/api/v1/audit/verify", headers=ADMIN).json()
    assert v["valid"] is True and v["checked"] == len(events) and v["brokenAt"] is None


def test_case_decision_rules(client):
    cid = start_call(client)
    assert client.post(f"/api/v1/cases/{cid}/decision", json={"action": "APPROVE", "reason": "x"},
                       headers=REVIEWER).status_code == 409  # still PROCESSING
    client.post(f"/api/v1/renewals/calls/{cid}/end", headers=VOICE)
    assert client.post(f"/api/v1/cases/{cid}/decision", json={"action": "APPROVE"},
                       headers=REVIEWER).status_code == 400
    assert client.post(f"/api/v1/cases/{cid}/decision", json={"action": "MAYBE", "reason": "x"},
                       headers=REVIEWER).status_code == 400


def test_audit_log_is_append_only(client):
    start_call(client)
    with pytest.raises(sqlite3.IntegrityError):
        with client.services.db.tx() as con:
            con.execute("UPDATE audit_events SET actor = 'mallory'")
    with pytest.raises(sqlite3.IntegrityError):
        with client.services.db.tx() as con:
            con.execute("DELETE FROM audit_events")


def test_verify_reports_a_tampered_event(client):
    cid = verified_call(client)
    events = audit(client, cid)
    target = events[1]["id"]
    with client.services.db.tx() as con:
        con.execute("DROP TRIGGER audit_events_no_update")
        con.execute("UPDATE audit_events SET payload = '{\"attempt\": 99}' WHERE id = ?", (target,))
    v = client.get("/api/v1/audit/verify", headers=ADMIN).json()
    assert v["valid"] is False and v["brokenAt"] == target
    assert v["detail"] == "hash does not match the event contents"
