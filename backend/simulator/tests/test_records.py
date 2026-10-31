from datetime import date

import pytest

from conftest import CUSTOMERS, session_for


def test_applications_stage(client):
    items = client.get("/v1/los/applications", headers=session_for(client, "CUST-1001")).json()["items"]
    assert [(a["ref"], a["stage"]) for a in items] == [("LA-24001", "DOCUMENT_VERIFICATION")]
    assert set(items[0]) == {"ref", "product", "amount", "stage", "stage_label", "submitted_on", "next_step"}


def test_loans_filtered_by_type(client):
    items = client.get("/v1/lms/loans", params={"type": "vehicle"}, headers=session_for(client, "CUST-1002")).json()["items"]
    assert [l["loan_id"] for l in items] == ["VL-31003"]
    loan = items[0]
    assert set(loan) == {"loan_id", "product", "product_type", "outstanding_principal", "next_instalment", "overdue", "status"}
    assert loan["next_instalment"]["amount"] == 9800
    assert loan["overdue"] is None


def test_overdue_kept_separate(client):
    loan = client.get("/v1/lms/loans", headers=session_for(client, "CUST-1003")).json()["items"][0]
    assert loan["overdue"]["amount"] == 9800
    assert loan["next_instalment"]["amount"] == 9800
    assert loan["overdue"]["since"] < loan["next_instalment"]["due_date"]


def test_schedule_has_a_due_entry(client):
    res = client.get("/v1/lms/loans/PL-31002/schedule", headers=session_for(client, "CUST-1002")).json()
    assert res["loan_id"] == "PL-31002"
    due = [i for i in res["items"] if i["status"] == "DUE"]
    assert len(due) == 1 and due[0]["amount"] == 12450


def test_unknown_loan_schedule_is_404(client):
    res = client.get("/v1/lms/loans/XX-1/schedule", headers=session_for(client, "CUST-1002"))
    assert res.status_code == 404


def test_failed_transaction_with_null_reason(client):
    items = client.get("/v1/cbs/transactions", params={"status": "FAILED"},
                       headers=session_for(client, "CUST-1004")).json()["items"]
    assert [(t["ref"], t["recorded_reason"]) for t in items] == [("TXN-88213", None)]
    assert set(items[0]) == {"ref", "date", "description", "amount", "direction", "status", "recorded_reason"}


def test_transaction_by_ref_and_limit(client):
    headers = session_for(client, "CUST-1004")
    items = client.get("/v1/cbs/transactions", params={"ref": "TXN-88214"}, headers=headers).json()["items"]
    assert [(t["ref"], t["status"], t["amount"]) for t in items] == [("TXN-88214", "PENDING", 2300)]
    assert len(client.get("/v1/cbs/transactions", params={"limit": 1}, headers=headers).json()["items"]) == 1


def test_accounts(client):
    items = client.get("/v1/cbs/accounts", headers=session_for(client, "CUST-1004")).json()["items"]
    assert items and set(items[0]) == {"account_id", "type", "masked_number", "balance", "currency"}


def test_claims_and_policies(client):
    headers = session_for(client, "CUST-1005")
    claims = client.get("/v1/insurance/claims", headers=headers).json()["items"]
    assert [(c["claim_no"], c["status"]) for c in claims] == [("CLM-7001", "UNDER_REVIEW")]
    policies = {p["policy_no"]: p["status"] for p in client.get("/v1/insurance/policies", headers=headers).json()["items"]}
    assert policies == {"HP-77001": "ACTIVE", "MP-77002": "LAPSED"}


LISTS = {
    "/v1/los/applications": ("ref", "applications"),
    "/v1/lms/loans": ("loan_id", "loans"),
    "/v1/cbs/accounts": ("account_id", "accounts"),
    "/v1/cbs/transactions": ("ref", "transactions"),
    "/v1/insurance/policies": ("policy_no", "policies"),
    "/v1/insurance/claims": ("claim_no", "claims"),
}


@pytest.mark.parametrize("path", LISTS)
@pytest.mark.parametrize("customer_ref", list(CUSTOMERS))
def test_lists_hold_only_the_session_customers_records(client, store, path, customer_ref):
    key, seed_attr = LISTS[path]
    owned = {r[key] for r in getattr(store, seed_attr) if r["customer_ref"] == customer_ref}
    items = client.get(path, params={"limit": 100} if "transactions" in path else None,
                       headers=session_for(client, customer_ref)).json()["items"]
    assert {i[key] for i in items} == owned


AMOUNT_KEYS = {"amount", "balance", "outstanding_principal", "premium", "sum_insured", "amount_claimed", "amount_approved"}
DATE_KEYS = {"submitted_on", "due_date", "since", "date", "premium_due_date"}


def _walk(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


@pytest.mark.parametrize("customer_ref", list(CUSTOMERS))
def test_amounts_are_integer_rupees_and_dates_iso(client, customer_ref):
    headers = session_for(client, customer_ref)
    for path in LISTS:
        for k, v in _walk(client.get(path, headers=headers).json()):
            if k in AMOUNT_KEYS and v is not None:
                assert isinstance(v, int) and not isinstance(v, bool), (path, k, v)
            if k in DATE_KEYS and v is not None:
                assert date.fromisoformat(v).isoformat() == v, (path, k, v)


def test_unknown_filters_are_422(client):
    headers = session_for(client, "CUST-1002")
    res = client.get("/v1/lms/loans", params={"type": "gold"}, headers=headers)
    assert res.status_code == 422
    assert res.json()["error"] == "VALIDATION_ERROR"
    assert client.get("/v1/cbs/transactions", params={"status": "LOST"}, headers=headers).status_code == 422
