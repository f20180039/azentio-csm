from conftest import session_for

OPS = ("ops", "ops")


def test_customer_profile_has_the_seeded_details_and_holdings(client):
    res = client.get("/v1/ops/customers/CUST-1002", auth=OPS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["customer"] == {"customer_ref": "CUST-1002", "first_name": "Rahul", "last_name": "Iyer",
                                "mobile": "9876500002", "dob": "1985-11-03"}
    assert [a["account_id"] for a in body["accounts"]] == ["ACC-20002"]
    assert {l["loan_id"] for l in body["loans"]} == {"PL-31002", "VL-31003"}
    assert "SR-40102" in [t["ref"] for t in body["tickets"]]
    assert set(body) == {"customer", "accounts", "loans", "applications", "transactions", "policies", "claims", "tickets", "complaints"}


def test_customer_profile_shows_records_raised_during_a_call(client):
    client.post("/v1/csm/tickets", headers=session_for(client, "CUST-1002"), json={
        "category": "STATEMENT", "summary": "Statement for 3 months", "details": {}, "call_id": "call-9"})
    tickets = [t["ref"] for t in client.get("/v1/ops/customers/CUST-1002", auth=OPS).json()["tickets"]]
    assert "SR-40200" in tickets


def test_a_customer_with_no_holdings_has_empty_lists(client):
    body = client.get("/v1/ops/customers/CUST-1009", auth=OPS).json()
    assert body["customer"]["mobile"] == "9380939280"
    assert all(body[k] == [] for k in body if k != "customer")


def test_customer_profile_needs_ops_credentials_and_a_known_ref(client):
    assert client.get("/v1/ops/customers/CUST-1002").status_code == 401
    assert client.get("/v1/ops/customers/CUST-1002", auth=("ops", "nope")).status_code == 401
    assert client.get("/v1/ops/customers/CUST-9999", auth=OPS).status_code == 404
