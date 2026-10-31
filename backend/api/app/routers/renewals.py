"""Renewals specialist endpoints."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import User, get_current_user
from app.store import store

router = APIRouter(prefix="/renewals", tags=["Renewals"])


class StartRenewalCallRequest(BaseModel):
    policyNumber: str | None = None
    policyNo: str | None = None


class VerifyRequest(BaseModel):
    dateOfBirth: str


class QuoteRequest(BaseModel):
    dropAddons: list[str] = Field(default_factory=list)
    paymentPlan: str = "ANNUAL"
    discountPercent: int = 0


class PaymentLinkRequest(BaseModel):
    quoteId: str


class HandoffRequest(BaseModel):
    reason: str
    callbackAt: str | None = None


class TurnRequest(BaseModel):
    role: str
    text: str
    at: str


@router.get("/queue")
def queue(user: User = Depends(get_current_user)):
    return {"items": store.get_renewals_queue()}


@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user)):
    return store.get_renewals_dashboard()


@router.post("/calls")
def create_call(body: StartRenewalCallRequest, user: User = Depends(get_current_user)):
    pno = body.policyNumber or body.policyNo or "POL-90124"
    return store.start_renewal_call(pno)


@router.get("/calls/{call_id}")
def get_call(call_id: str, user: User = Depends(get_current_user)):
    call = store.get_renewal_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


@router.post("/calls/{call_id}/verify")
def verify_call(call_id: str, body: VerifyRequest, user: User = Depends(get_current_user)):
    return {"verified": True}


@router.get("/calls/{call_id}/policy")
def get_policy(call_id: str, user: User = Depends(get_current_user)):
    return {
        "policyNo": "POL-90124",
        "customerName": "Asha Verma",
        "product": "Comprehensive Motor",
        "premium": 12800,
        "expiryDate": "2026-11-20",
        "addons": ["Zero Depreciation", "Roadside Assistance"],
    }


@router.get("/calls/{call_id}/options")
def get_options(call_id: str, user: User = Depends(get_current_user)):
    return {
        "paymentPlans": ["ANNUAL", "SEMI_ANNUAL", "MONTHLY"],
        "maxDiscountPercent": 10,
        "removableAddons": ["Roadside Assistance"],
    }


@router.post("/calls/{call_id}/quote")
def quote(call_id: str, body: QuoteRequest, user: User = Depends(get_current_user)):
    return {
        "quoteId": "QTE-8841",
        "originalPremium": 12800,
        "finalPremium": int(12800 * (1 - body.discountPercent / 100)),
        "discountApplied": body.discountPercent,
    }


@router.post("/calls/{call_id}/payment-link")
def payment_link(call_id: str, body: PaymentLinkRequest, user: User = Depends(get_current_user)):
    return {
        "link": f"https://pay.azentio-demo.com/{body.quoteId}",
        "expiresInMinutes": 60,
    }


@router.post("/calls/{call_id}/handoff")
def handoff(call_id: str, body: HandoffRequest, user: User = Depends(get_current_user)):
    return {"status": "HANDOFF_QUEUED", "reason": body.reason}


@router.post("/calls/{call_id}/turns")
def turn(call_id: str, body: TurnRequest, user: User = Depends(get_current_user)):
    return {"seq": 1}


@router.post("/calls/{call_id}/end")
def end(call_id: str, user: User = Depends(get_current_user)):
    return {"ended": True}
