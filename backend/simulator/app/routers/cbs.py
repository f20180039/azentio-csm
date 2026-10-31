"""Core Banking System (CBS) and Loan Management (LMS) Simulator Router."""
from datetime import date, timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.security.auth import TokenData, get_current_user
from app.security.audit import audit_ledger

router = APIRouter(prefix="/v1/cbs", tags=["Core Banking & LMS Integrations"])

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


class PrepaymentCalcRequest(BaseModel):
    loan_id: str
    prepayment_amount: float


class ClaimIntakeRequest(BaseModel):
    policy_id: str
    incident_date: str
    location: str
    damage_description: str
    contact_number: str


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
