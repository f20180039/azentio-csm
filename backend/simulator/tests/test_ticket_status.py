from app.config import settings
from conftest import session_for

OPS = ("ops", "ops")


def ticket_as(client, customer_ref: str, ref: str) -> dict:
    res = client.get(f"/v1/csm/tickets/{ref}", headers=session_for(client, customer_ref))
    assert res.status_code == 200, res.text
    return res.json()


def patch_ticket(client, ref: str, body: dict, auth=OPS):
    return client.patch(f"/v1/ops/tickets/{ref}", json=body, auth=auth)


def test_new_ticket_has_department_and_progress(client):
    headers = session_for(client, "CUST-1002")
    res = client.post("/v1/csm/tickets", headers=headers, json={
        "category": "STATEMENT", "summary": "Statement for 6 months", "call_id": "call-1"})
    assert res.status_code == 201, res.text
    ref = res.json()["ref"]

    got = client.get(f"/v1/csm/tickets/{ref}", headers=headers).json()
    assert got["department"] == "Account Services"
    assert got["progress"]
    assert got["eta_days"] == settings.ticket_eta_days

    ops_item = next(i for i in client.get("/v1/ops/records", params={"kind": "ticket"}, auth=OPS).json()["items"]
                    if i["ref"] == ref)
    assert ops_item["department"] == "Account Services" and ops_item["progress"] == got["progress"]
    profile_item = next(t for t in client.get("/v1/ops/customers/CUST-1002", auth=OPS).json()["tickets"]
                        if t["ref"] == ref)
    assert profile_item["department"] == "Account Services" and profile_item["progress"] == got["progress"]


def test_ops_can_move_a_ticket_to_each_status(client):
    headers = session_for(client, "CUST-1002")
    res = client.post("/v1/csm/tickets", headers=headers, json={
        "category": "ACCOUNT_DOCUMENT", "summary": "Interest certificate by post", "call_id": "call-1"})
    assert res.json()["ref"] == "SR-40200"

    moved = patch_ticket(client, "SR-40200", {"status": "AWAITING_INFO", "progress": "Waiting for the delivery address"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "AWAITING_INFO" and moved.json()["progress"] == "Waiting for the delivery address"
    got = ticket_as(client, "CUST-1002", "SR-40200")
    assert got["status"] == "AWAITING_INFO" and got["progress"] == "Waiting for the delivery address"

    patch_ticket(client, "SR-40200", {"status": "REJECTED", "progress": "Rejected: no address was given."})
    got = ticket_as(client, "CUST-1002", "SR-40200")
    assert got["status"] == "REJECTED" and got["progress"] == "Rejected: no address was given."

    patch_ticket(client, "SR-40200", {"status": "RESOLVED"})  # no progress: the note is kept
    got = ticket_as(client, "CUST-1002", "SR-40200")
    assert got["status"] == "RESOLVED" and got["progress"] == "Rejected: no address was given."


def test_seed_ticket_update_is_undone_by_reset(client):
    assert ticket_as(client, "CUST-1002", "SR-40102")["status"] == "IN_PROGRESS"
    moved = patch_ticket(client, "SR-40102", {"status": "RESOLVED", "progress": "Statement emailed."})
    assert moved.status_code == 200, moved.text
    got = ticket_as(client, "CUST-1002", "SR-40102")
    assert got["status"] == "RESOLVED" and got["progress"] == "Statement emailed."

    assert client.post("/v1/ops/reset", auth=OPS).status_code == 200
    got = ticket_as(client, "CUST-1002", "SR-40102")
    assert got["status"] == "IN_PROGRESS" and got["progress"] == "With the Account Services team."


def test_ticket_update_needs_ops_and_a_known_status_and_ref(client):
    assert client.patch("/v1/ops/tickets/SR-40102", json={"status": "RESOLVED"}).status_code == 401
    assert patch_ticket(client, "SR-40102", {"status": "RESOLVED"}, auth=("ops", "nope")).status_code == 401

    bad = patch_ticket(client, "SR-40102", {"status": "LOST"})
    assert bad.status_code == 422
    assert bad.json()["error"] == "VALIDATION_ERROR"

    missing = patch_ticket(client, "SR-99999", {"status": "RESOLVED"})
    assert missing.status_code == 404
    assert missing.json()["error"] == "NOT_FOUND"


def test_seed_has_each_open_and_closed_status(client):
    rejected = ticket_as(client, "CUST-1003", "SR-40103")
    assert rejected["status"] == "REJECTED" and rejected["category"] == "ADDRESS_CHANGE"
    assert rejected["department"] == "KYC & Records"
    assert rejected["progress"] == "Rejected: the address proof was unreadable. Please submit a clear copy."

    awaiting = ticket_as(client, "CUST-1004", "SR-40104")
    assert awaiting["status"] == "AWAITING_INFO" and awaiting["category"] == "ACCOUNT_DOCUMENT"
    assert awaiting["department"] == "Account Services"
    assert awaiting["progress"] == "Waiting for the customer to confirm the delivery address."

    resolved = ticket_as(client, "CUST-1005", "SR-40105")
    assert resolved["status"] == "RESOLVED" and resolved["category"] == "STATEMENT"
    assert resolved["department"] == "Account Services"
    assert resolved["progress"] == "Statement sent to the registered email address."

    in_progress = ticket_as(client, "CUST-1002", "SR-40102")
    assert in_progress["status"] == "IN_PROGRESS" and in_progress["progress"] == "With the Account Services team."
