from datetime import date
from pathlib import Path

from app.enums import (
    ClaimStatus,
    ComplaintCategory,
    InstalmentStatus,
    PolicyStatus,
    ProductType,
    Severity,
    Stage,
    TicketCategory,
    TicketStatus,
    TxnStatus,
)
from app.store import BankStore, DEFAULT_SEED_DIR


def test_enums_defined():
    assert Stage.DOCUMENT_VERIFICATION.value == "DOCUMENT_VERIFICATION"
    assert ProductType.VEHICLE.value == "vehicle"
    assert InstalmentStatus.DUE.value == "DUE"
    assert TicketCategory.STATEMENT.value == "STATEMENT"
    assert TicketStatus.OPEN.value == "OPEN"
    assert ComplaintCategory.UNAUTHORISED_TRANSACTION.value == "UNAUTHORISED_TRANSACTION"
    assert Severity.HIGH.value == "HIGH"
    assert PolicyStatus.ACTIVE.value == "ACTIVE"
    assert ClaimStatus.UNDER_REVIEW.value == "UNDER_REVIEW"


def test_seeds_load_9_customers(tmp_path: Path):
    db_file = tmp_path / "test_sim.db"
    store = BankStore(db_path=db_file, seed_dir=DEFAULT_SEED_DIR)
    assert len(store.customers) == 9

    # Verify all expected customer refs exist
    expected_refs = {f"CUST-100{i}" for i in range(1, 10)}
    assert set(store.customers.keys()) == expected_refs

    # Check mobile and dob for Asha Verma
    asha = store.get_customer("CUST-1001")
    assert asha is not None
    assert asha["first_name"] == "Asha"
    assert asha["mobile"] == "9876500001"
    assert asha["dob"] == "1990-04-12"


def test_every_loan_next_instalment_in_future(tmp_path: Path):
    db_file = tmp_path / "test_sim.db"
    today = date.today()
    store = BankStore(db_path=db_file, seed_dir=DEFAULT_SEED_DIR, today=today)

    assert len(store.loans) > 0
    today_str = today.isoformat()
    for loan in store.loans:
        next_inst = loan.get("next_instalment")
        assert next_inst is not None, f"Loan {loan['loan_id']} missing next_instalment"
        assert next_inst["due_date"] > today_str, (
            f"Loan {loan['loan_id']} due_date {next_inst['due_date']} is not after {today_str}"
        )


def test_vl31007_overdue_amount(tmp_path: Path):
    db_file = tmp_path / "test_sim.db"
    store = BankStore(db_path=db_file, seed_dir=DEFAULT_SEED_DIR)
    vl31007 = store.get_loan("VL-31007")
    assert vl31007 is not None
    assert vl31007["overdue"] is not None
    assert vl31007["overdue"]["amount"] == 9800


def test_ticket_creation_persistence_and_reset(tmp_path: Path):
    db_file = tmp_path / "test_sim.db"
    store1 = BankStore(db_path=db_file, seed_dir=DEFAULT_SEED_DIR)

    # 1. Created ticket gets ref SR-40200
    res = store1.create_ticket(
        customer_ref="CUST-1002",
        category=TicketCategory.REPAYMENT_SCHEDULE,
        summary="Repayment schedule request",
        details={"loan_id": "PL-31002"},
        call_id="call-test-01",
    )
    assert res["ref"] == "SR-40200"
    assert res["status"] == "OPEN"
    assert res["eta_days"] == 2

    # 2. Survives a store reload
    store2 = BankStore(db_path=db_file, seed_dir=DEFAULT_SEED_DIR)
    t = store2.get_ticket("SR-40200")
    assert t is not None
    assert t["ref"] == "SR-40200"
    assert t["summary"] == "Repayment schedule request"
    assert t["customer_ref"] == "CUST-1002"

    # Also listed in customer tickets
    cust_tickets = store2.get_tickets("CUST-1002")
    refs = [x["ref"] for x in cust_tickets]
    assert "SR-40200" in refs
    assert "SR-40102" in refs  # Seed ticket

    # 3. reset() removes it
    store2.reset()
    assert store2.get_ticket("SR-40200") is None
    # Customer tickets now only has the seed ticket
    cust_tickets_after_reset = store2.get_tickets("CUST-1002")
    refs_after = [x["ref"] for x in cust_tickets_after_reset]
    assert "SR-40200" not in refs_after
    assert "SR-40102" in refs_after

    # Next ticket created starts back at SR-40200
    res2 = store2.create_ticket(
        customer_ref="CUST-1002",
        category=TicketCategory.STATEMENT,
        summary="New statement request",
        details={},
        call_id="call-test-02",
    )
    assert res2["ref"] == "SR-40200"


def test_complaints_routed_and_escalations(tmp_path: Path):
    db_file = tmp_path / "test_sim.db"
    store = BankStore(db_path=db_file, seed_dir=DEFAULT_SEED_DIR)

    # Complaint with high severity or unauthorised transaction is escalated
    c1 = store.create_complaint(
        customer_ref="CUST-1008",
        category=ComplaintCategory.UNAUTHORISED_TRANSACTION,
        description="Card charged 48999",
        severity=Severity.HIGH,
        call_id="call-c1",
    )
    assert c1["ref"] == "CMP-50200"
    assert c1["escalated"] is True

    # Complaint with low severity is not escalated
    c2 = store.create_complaint(
        customer_ref="CUST-1006",
        category=ComplaintCategory.SERVICE_EXPERIENCE,
        description="Long queue",
        severity=Severity.LOW,
        call_id="call-c2",
    )
    assert c2["ref"] == "CMP-50201"
    assert c2["escalated"] is False

    # Routed query
    rq = store.create_routed("Can I get a flight?", "unsupported request", "call-rq")
    assert rq["ref"] == "RQ-60200"

    # Escalation
    esc = store.create_escalation("fraud", "Card fraud reported", "call-esc", "CUST-1008")
    assert esc["ref"] == "ESC-70200"
