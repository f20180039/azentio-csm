"""Level 2: complaints keep the caller's words and a linked reference; escalations carry a category and linked records."""
from conftest import session_for

OPS = ("ops", "ops")


def records(client, kind):
    res = client.get("/v1/ops/records", params={"kind": kind}, auth=OPS)
    assert res.status_code == 200, res.text
    return res.json()["items"]


def test_complaint_keeps_the_callers_words_and_reference(client):
    headers = session_for(client, "CUST-1002")
    res = client.post("/v1/csm/complaints", headers=headers, json={
        "category": "FAILED_TRANSACTION", "severity": "MEDIUM", "call_id": "call-1",
        "description": "Failed NEFT transfer, no reason recorded",
        "original_statement": "my fifteen thousand transfer to Rajesh failed yesterday",
        "related_ref": "TXN-88213"})
    assert res.status_code == 201, res.text
    ref = res.json()["ref"]

    ops_item = next(i for i in records(client, "complaint") if i["ref"] == ref)
    assert ops_item["summary"] == "Failed NEFT transfer, no reason recorded"
    assert ops_item["original_statement"] == "my fifteen thousand transfer to Rajesh failed yesterday"
    assert ops_item["related_ref"] == "TXN-88213"

    profile = client.get("/v1/ops/customers/CUST-1002", auth=OPS).json()
    profile_item = next(c for c in profile["complaints"] if c["ref"] == ref)
    assert profile_item["description"] == "Failed NEFT transfer, no reason recorded"
    assert profile_item["original_statement"] == "my fifteen thousand transfer to Rajesh failed yesterday"
    assert profile_item["related_ref"] == "TXN-88213"


def test_complaint_without_new_fields_still_works(client):
    headers = session_for(client, "CUST-1002")
    res = client.post("/v1/csm/complaints", headers=headers, json={
        "category": "INCORRECT_CHARGE", "severity": "LOW", "call_id": "call-1", "description": "Double ATM fee"})
    assert res.status_code == 201, res.text
    ref = res.json()["ref"]
    ops_item = next(i for i in records(client, "complaint") if i["ref"] == ref)
    assert ops_item["original_statement"] is None and ops_item["related_ref"] is None
    profile_item = next(c for c in client.get("/v1/ops/customers/CUST-1002", auth=OPS).json()["complaints"]
                        if c["ref"] == ref)
    assert profile_item["original_statement"] is None and profile_item["related_ref"] is None


def test_escalation_has_category_and_linked_records(client):
    res = client.post("/v1/csm/escalations", headers=session_for(client, "CUST-1002"), json={
        "reason": "Customer asked twice, ticket still open", "summary": "SR-40200 not moving", "call_id": "call-2",
        "category": "UNRESOLVED", "related_refs": ["SR-40200", "CMP-50200"]})
    assert res.status_code == 201, res.text
    ref = res.json()["ref"]

    ops_item = next(i for i in records(client, "escalation") if i["ref"] == ref)
    assert ops_item["category"] == "UNRESOLVED"
    assert ops_item["related_refs"] == ["SR-40200", "CMP-50200"]
    assert ops_item["customer_ref"] == "CUST-1002"


def test_escalation_without_new_fields_still_works(client):
    res = client.post("/v1/csm/escalations", json={"reason": "UNRESOLVED: x", "summary": "needs help", "call_id": "c4"})
    assert res.status_code == 201, res.text
    ref = res.json()["ref"]
    ops_item = next(i for i in records(client, "escalation") if i["ref"] == ref)
    assert ops_item["category"] is None
    assert ops_item["related_refs"] in (None, [])


def test_unknown_escalation_category_is_422(client):
    res = client.post("/v1/csm/escalations", json={
        "reason": "x", "summary": "y", "call_id": "c", "category": "ANGRY"})
    assert res.status_code == 422, res.text


def test_other_record_kinds_have_null_l2_fields(client):
    headers = session_for(client, "CUST-1002")
    client.post("/v1/csm/tickets", headers=headers, json={"category": "STATEMENT", "summary": "s", "call_id": "c"})
    ticket = records(client, "ticket")[0]
    assert ticket["original_statement"] is None and ticket["related_ref"] is None and ticket["related_refs"] is None
