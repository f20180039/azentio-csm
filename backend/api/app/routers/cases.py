"""Case Intelligence endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import User, get_current_user

router = APIRouter(prefix="/cases", tags=["Cases"])


class DecisionRequest(BaseModel):
    action: str
    comment: str | None = None


@router.get("")
def list_cases(user: User = Depends(get_current_user)):
    return {
        "items": [
            {
                "id": "CASE-101",
                "caseType": "demo",
                "customerRef": "CUST-1001",
                "status": "OPEN",
                "score": 0.35,
                "createdAt": "2026-10-31T05:00:00Z",
                "summary": "Income verification check",
            },
            {
                "id": "CASE-102",
                "caseType": "demo",
                "customerRef": "CUST-1004",
                "status": "REVIEW",
                "score": 0.82,
                "createdAt": "2026-10-31T05:15:00Z",
                "summary": "High risk duplicate transfer flagged",
            },
        ]
    }


@router.get("/{case_id}")
def get_case(case_id: str, user: User = Depends(get_current_user)):
    return {
        "id": case_id,
        "caseType": "demo",
        "customerRef": "CUST-1001",
        "status": "OPEN",
        "score": 0.35,
        "createdAt": "2026-10-31T05:00:00Z",
        "summary": "Income verification check",
        "findings": [],
    }


@router.post("/{case_id}/decision")
def record_decision(case_id: str, body: DecisionRequest, user: User = Depends(get_current_user)):
    return {"id": case_id, "action": body.action, "recorded": True}
