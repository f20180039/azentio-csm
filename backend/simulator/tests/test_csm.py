from conftest import session_for, verify

OPS = ("ops", "ops")


def records(client, kind=None):
    res = client.get("/v1/ops/records", params={"kind": kind} if kind else None, auth=OPS)
    assert res.status_code == 200, res.text
    return res.json()["items"]


def test_create_and_read_ticket(client):
    headers = session_for(client, "CUST-1002")
    res = client.post("/v1/csm/tickets", headers=headers, json={
        "category": "REPAYMENT_SCHEDULE", "summary": "Schedule for PL-31002", "details": {"loan_id": "PL-31002"},
        "call_id": "call-1"})
    assert res.status_code == 201
    assert res.json()["ref"] == "SR-40200"
    assert res.json()["status"] == "OPEN"
    assert isinstance(res.json()["eta_days"], int)

    got = client.get("/v1/csm/tickets/SR-40200", headers=headers).json()
    assert got["ref"] == "SR-40200" and got["category"] == "REPAYMENT_SCHEDULE" and got["status"] == "OPEN"
    assert set(got) == {"ref", "category", "status", "summary", "details", "created_on", "updated_on"}
    assert got["details"] == {"loan_id": "PL-31002"}

    mine = [t["ref"] for t in client.get("/v1/csm/tickets", headers=headers).json()["items"]]
    assert {"SR-40200", "SR-40102"} <= set(mine)


def test_another_customers_ticket_is_403(client):
    res = client.get("/v1/csm/tickets/SR-40102", headers=session_for(client, "CUST-1003"))
    assert res.status_code == 403
    assert res.json()["error"] == "NOT_YOUR_RECORD"


def test_ticket_without_session_is_401(client):
    res = client.post("/v1/csm/tickets", json={"category": "STATEMENT", "summary": "x", "call_id": "c"})
    assert res.status_code == 401
    assert res.json()["error"] == "NOT_VERIFIED"


def test_unauthorised_transaction_complaint_escalates(client):
    res = client.post("/v1/csm/complaints", headers=session_for(client, "CUST-1008"), json={
        "category": "UNAUTHORISED_TRANSACTION", "description": "Card debit TXN-90011 not made by me",
        "severity": "MEDIUM", "call_id": "call-2"})
    assert res.status_code == 201
    assert res.json() == {"ref": "CMP-50200", "status": "OPEN", "escalated": True}


def test_high_severity_escalates_and_low_service_does_not(client):
    headers = session_for(client, "CUST-1006")
    high = client.post("/v1/csm/complaints", headers=headers, json={
        "category": "INCORRECT_CHARGE", "description": "x", "severity": "HIGH", "call_id": "c"}).json()
    low = client.post("/v1/csm/complaints", headers=headers, json={
        "category": "SERVICE_EXPERIENCE", "description": "x", "severity": "LOW", "call_id": "c"}).json()
    assert high["escalated"] is True
    assert low["escalated"] is False


def test_routed_works_without_session(client):
    res = client.post("/v1/csm/routed", json={
        "query_text": "Can you increase my credit card limit?", "reason": "Not supported by this desk",
        "call_id": "call-3", "customer_ref": None})
    assert res.status_code == 201
    assert res.json() == {"ref": "RQ-60200"}


def test_escalation_session_optional(client):
    anon = client.post("/v1/csm/escalations", json={"reason": "UNRESOLVED: x", "summary": "needs help", "call_id": "c4"})
    assert anon.status_code == 201 and anon.json() == {"ref": "ESC-70200"}
    signed = client.post("/v1/csm/escalations", headers=session_for(client, "CUST-1008"),
                         json={"reason": "SENSITIVE: fraud", "summary": "unauthorised debit", "call_id": "c5"})
    assert signed.json() == {"ref": "ESC-70201"}
    by_ref = {r["ref"]: r for r in records(client, "escalation")}
    assert by_ref["ESC-70200"]["customer_ref"] is None
    assert by_ref["ESC-70201"]["customer_ref"] == "CUST-1008"


def test_unknown_category_is_422(client):
    headers = session_for(client, "CUST-1002")
    assert client.post("/v1/csm/tickets", headers=headers,
                       json={"category": "LOAN_WAIVER", "summary": "x", "call_id": "c"}).status_code == 422
    res = client.post("/v1/csm/complaints", headers=headers,
                      json={"category": "RUDE", "description": "x", "severity": "LOW", "call_id": "c"})
    assert res.status_code == 422
    assert res.json()["error"] == "VALIDATION_ERROR"


def test_ops_records_need_basic_auth(client):
    client.post("/v1/csm/routed", json={"query_text": "Weather?", "reason": "Out of scope", "call_id": "c6"})
    assert client.get("/v1/ops/records", params={"kind": "routed"}).status_code == 401
    assert client.get("/v1/ops/records", params={"kind": "routed"}, auth=("ops", "nope")).status_code == 401
    items = records(client, "routed")
    assert len(items) == 1
    item = items[0]
    assert set(item) == {"ref", "kind", "category", "status", "summary", "customer_ref", "call_id", "created_at", "escalated"}
    assert item["kind"] == "routed" and item["call_id"] == "c6"
    assert "Weather?" in item["summary"] and "Out of scope" in item["summary"]


def test_ops_records_newest_first_and_unknown_kind_422(client):
    headers = session_for(client, "CUST-1002")
    for summary in ("first", "second"):
        client.post("/v1/csm/tickets", headers=headers, json={"category": "STATEMENT", "summary": summary, "call_id": "c"})
    items = records(client, "ticket")
    assert [i["summary"] for i in items[:2]] == ["second", "first"]
    assert items[0]["call_id"] == "c" and items[0]["created_at"]
    assert client.get("/v1/ops/records", params={"kind": "card"}, auth=OPS).status_code == 422
    assert {i["kind"] for i in records(client)} >= {"ticket", "complaint"}


def test_ops_reset_empties_writes_and_lockouts(client):
    headers = session_for(client, "CUST-1002")
    client.post("/v1/csm/tickets", headers=headers, json={"category": "STATEMENT", "summary": "x", "call_id": "c"})
    client.post("/v1/csm/routed", json={"query_text": "q", "reason": "r", "call_id": "c"})
    for _ in range(3):
        verify(client, "CUST-1003", "2000-01-01", call_id="c")
    assert verify(client, "CUST-1003", call_id="c").status_code == 423

    assert client.post("/v1/ops/reset").status_code == 401
    assert client.post("/v1/ops/reset", auth=OPS).status_code == 200

    assert records(client, "routed") == []
    assert all(t["ref"] != "SR-40200" for t in records(client, "ticket"))
    assert client.get("/v1/csm/tickets", headers=headers).status_code == 401  # sessions are writes too
    assert verify(client, "CUST-1003", call_id="c").status_code == 200
    new = client.post("/v1/csm/tickets", headers=session_for(client, "CUST-1002"),
                      json={"category": "STATEMENT", "summary": "x", "call_id": "c"})
    assert new.json()["ref"] == "SR-40200"


def test_security_escalation_listed_in_ops(client):
    for ref in ("CUST-1001", "CUST-1002", "CUST-1003"):
        verify(client, ref, "2000-01-01", call_id="bf", caller_ref="+919811100000")
    esc = records(client, "escalation")
    assert len(esc) == 1
    assert esc[0]["category"] == "SECURITY"
    assert esc[0]["summary"].startswith("Repeated failed verification across 3 customers")
    assert esc[0]["call_id"] == "bf"


def test_cors_allows_operator_panel_with_authorization(client):
    res = client.options("/v1/ops/records", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization"})
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "authorization" in res.headers["access-control-allow-headers"].lower()


def test_seed_ticket_view_has_empty_details(client):
    got = client.get("/v1/csm/tickets/SR-40102", headers=session_for(client, "CUST-1002")).json()
    assert got["details"] == {} and got["status"] == "IN_PROGRESS"


def test_complaint_status_by_reference_for_its_owner_only(client):
    got = client.get("/v1/csm/complaints/CMP-50011", headers=session_for(client, "CUST-1006"))
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["ref"] == "CMP-50011" and body["status"] == "OPEN" and body["category"] == "INCORRECT_CHARGE"
    assert "customer_ref" not in body and "call_id" not in body
    other = client.get("/v1/csm/complaints/CMP-50011", headers=session_for(client, "CUST-1002"))
    assert other.status_code == 403 and other.json()["error"] == "NOT_YOUR_RECORD"
    assert client.get("/v1/csm/complaints/CMP-99999", headers=session_for(client, "CUST-1006")).status_code == 404
    assert client.get("/v1/csm/complaints/CMP-50011").status_code == 401
