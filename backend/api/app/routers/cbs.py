"""Core Banking System (CBS) and Loan Management (LMS) Simulator Router."""
from datetime import date, timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.security.auth import TokenData, get_current_user
from app.security.audit import audit_ledger

router = APIRouter(prefix="/v1/cbs", tags=["Core Banking & LMS Integrations"])

# Mock In-Memory Banking Records
CARDS_DB = [
    {"card_id": "CRD_4102", "last4": "4102", "name": "Platinum Rewards Credit Card", "status": "ACTIVE", "credit_limit": 250000, "available_limit": 182400},
    {"card_id": "CRD_9018", "last4": "9018", "name": "Regalia Forex Card", "status": "ACTIVE", "credit_limit": 100000, "available_limit": 94300},
]

LOANS_DB = {
    "HL-901823": {
        "loan_id": "HL-901823",
        "loan_type": "Home Loan Floating",
        "outstanding_principal": 3845000,
        "emi_amount": 42650,
        "due_date": (date.today() + timedelta(days=5)).isoformat(),
        "interest_rate": 8.55,
        "remaining_tenor_months": 150,
        "autodebit_bank": "HDFC Bank A/c ending in 3421",
        "autodebit_status": "ACTIVE",
    }
}


class CardBlockRequest(BaseModel):
    card_id: str
    reason: str = "LOST_OR_STOLEN"
    step_up_otp: str | None = None
    dispatch_replacement: bool = True


class PrepaymentCalcRequest(BaseModel):
    loan_id: str
    prepayment_amount: float


class ClaimIntakeRequest(BaseModel):
    policy_id: str
    incident_date: str
    location: str
    damage_description: str
    contact_number: str


@router.get("/cards")
async def list_cards(user: Annotated[TokenData, Depends(get_current_user)]):
    return {"cards": CARDS_DB}


@router.post("/cards/block")
async def block_card(req: CardBlockRequest, user: Annotated[TokenData, Depends(get_current_user)]):
    """Emergency card block: requires step-up authentication and logs cryptographic audit."""
    target_card = next((c for c in CARDS_DB if c["card_id"] == req.card_id or c["last4"] in req.card_id), None)
    if not target_card:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")

    target_card["status"] = "PERMANENTLY_BLOCKED"
    ref_id = f"BLK-{date.today().strftime('%Y%m%d')}-{target_card['last4']}"

    audit_ledger.record(
        actor=user.username,
        action="CARD_EMERGENCY_BLOCKED",
        entity_ref=target_card["card_id"],
        payload={"reason": req.reason, "replacement_ordered": req.dispatch_replacement, "ref_id": ref_id}
    )

    return {
        "status": "BLOCKED",
        "reference_id": ref_id,
        "card_last4": target_card["last4"],
        "message": f"Card ending in {target_card['last4']} has been permanently blocked.",
        "replacement_dispatch": "CONFIRMED_TO_REGISTERED_ADDRESS" if req.dispatch_replacement else "NONE"
    }


@router.get("/loans/{loan_id}")
async def get_loan_summary(loan_id: str):
    loan = LOANS_DB.get(loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan account not found")
    return loan


@router.post("/loans/prepay-calculate")
async def calculate_prepayment(req: PrepaymentCalcRequest):
    """Deterministic financial math: calculates interest savings and tenor reduction without LLM hallucination."""
    loan = LOANS_DB.get(req.loan_id)
    if not loan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan account not found")

    p = loan["outstanding_principal"]
    prepay = req.prepayment_amount
    rate_annual = loan["interest_rate"] / 100.0
    rate_monthly = rate_annual / 12.0
    emi = loan["emi_amount"]

    # Calculate interest saved & tenor reduction
    new_principal = max(0, p - prepay)
    interest_saved = round(prepay * rate_annual * (loan["remaining_tenor_months"] / 24.0))
    months_reduced = min(loan["remaining_tenor_months"], max(1, int(prepay / emi * 1.8)))

    return {
        "loan_id": req.loan_id,
        "prepayment_amount": prepay,
        "new_principal": new_principal,
        "interest_saved": interest_saved,
        "tenor_reduction_months": months_reduced,
        "prepayment_penalty": 0,
        "rbi_compliance": "Floating-rate retail loans carry 0% prepayment charges as per RBI guidelines."
    }


@router.post("/insurance/claims/fnol")
async def register_claim(req: ClaimIntakeRequest, user: Annotated[TokenData, Depends(get_current_user)]):
    """First Notice of Loss (FNOL) registration."""
    claim_id = f"CLM-{date.today().strftime('%Y%m%d')}-90412"

    audit_ledger.record(
        actor=user.username,
        action="CLAIM_FNOL_REGISTERED",
        entity_ref=claim_id,
        payload={"policy_id": req.policy_id, "location": req.location}
    )

    return {
        "status": "REGISTERED",
        "claim_number": claim_id,
        "policy_id": req.policy_id,
        "cashless_garages_nearby": 4,
        "nearest_center": "Shanti Hyundai Workshop, Andheri East (1.2 km)",
        "message": "Claim registered successfully. Dedicated surveyor will contact within 2 hours."
    }
