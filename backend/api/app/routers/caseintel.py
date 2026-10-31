"""Case Intelligence & Renewals Desk Endpoints for Frontend Compatibility."""
from datetime import date, timedelta
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.security.auth import TokenData, get_current_user

router = APIRouter(prefix="/v1", tags=["Case Intelligence & Renewals Desk"])

# Demo Rule Packs
RULE_PACKS = [
    {
        "caseType": "demo",
        "label": "Demo Documents & Red-Team Suite",
        "extractionSchema": "demo",
        "routing": {"autoClearBelow": 0.2, "escalateAtOrAbove": 0.8},
        "rules": [
            {"id": "CORE-DUPLICATE-DOC", "weight": 0.5, "rationale": "Same file already seen in another case"},
            {"id": "CORE-HIDDEN-TEXT", "weight": 0.6, "rationale": "Text a human cannot see is a manipulation signal"},
            {"id": "CORE-INJECTION", "weight": 0.8, "rationale": "Instructions aimed at the AI inside a document"},
            {"id": "DEMO-LARGE-AMOUNT", "weight": 0.3, "rationale": "Amounts above configured threshold", "params": {"threshold": 100000}}
        ]
    },
    {
        "caseType": "bank_statement",
        "label": "Bank Statements (BFSI Pack)",
        "extractionSchema": "bank_statement",
        "routing": {"autoClearBelow": 0.25, "escalateAtOrAbove": 0.75},
        "rules": [
            {"id": "CORE-DUPLICATE-DOC", "weight": 0.5, "rationale": "Duplicate document hash detected"},
            {"id": "BS-BALANCE-CHAIN", "weight": 0.7, "rationale": "Opening balance ± amount must match closing balance"},
            {"id": "BS-WINDOW-DRESSING", "weight": 0.4, "rationale": "Large round credit shortly before statement end"}
        ]
    }
]

# Sample Renewal Queue Items
RENEWAL_QUEUE = [
    {
        "policyId": "LL-MOT-20418",
        "holderName": "Meera Iyer",
        "product": "Motor comprehensive",
        "expiresOn": (date.today() + timedelta(days=9)).isoformat(),
        "daysToExpiry": 9,
        "score": 0.34,
        "signals": [
            {"code": "CLAIM_FREE_3Y", "label": "Claim-free for 3 years", "severity": "LOW", "weight": 0.1},
            {"code": "LATE_RENEWER", "label": "Renewed late last year", "severity": "MEDIUM", "weight": 0.24}
        ],
        "route": "AGENT_CALL"
    },
    {
        "policyId": "LL-HLT-11873",
        "holderName": "Arjun Nair",
        "product": "Health floater",
        "expiresOn": (date.today() + timedelta(days=14)).isoformat(),
        "daysToExpiry": 14,
        "score": 0.58,
        "signals": [
            {"code": "PREMIUM_JUMP", "label": "Premium up 18%", "severity": "MEDIUM", "weight": 0.3},
            {"code": "ADDON_DROP_HISTORY", "label": "Dropped an add-on last time", "severity": "LOW", "weight": 0.15}
        ],
        "route": "AGENT_CALL"
    },
    {
        "policyId": "LL-MOT-20977",
        "holderName": "Kavita Rao",
        "product": "Motor third party",
        "expiresOn": (date.today() + timedelta(days=3)).isoformat(),
        "daysToExpiry": 3,
        "score": 0.86,
        "signals": [
            {"code": "OPEN_CLAIM", "label": "Open claim on this policy", "severity": "HIGH", "weight": 0.5},
            {"code": "DISPUTE", "label": "Premium dispute logged", "severity": "HIGH", "weight": 0.36}
        ],
        "route": "HUMAN_ONLY"
    }
]


@router.get("/me")
async def get_me(user: Annotated[TokenData, Depends(get_current_user)]):
    """Called by frontend on login with Basic Auth."""
    if user.username == "anonymous":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    roles = ["ANALYST"]
    if user.role in ("REVIEWER", "ADMIN"):
        roles.append("REVIEWER")
    if user.role == "ADMIN":
        roles.append("ADMIN")

    return {
        "username": user.username,
        "roles": roles,
        "tenant_id": user.tenant_id
    }


@router.get("/packs")
async def get_packs():
    """Returns rule packs for verification and display."""
    return RULE_PACKS


@router.get("/stats")
async def get_stats():
    """Returns operational throughput and latency statistics."""
    return {
        "byStatus": {"CLEARED": 128, "ESCALATED": 14, "REJECTED": 6, "PENDING_REVIEW": 22},
        "jobsPending": 0,
        "p50Ms": 850,
        "p95Ms": 1420,
        "cacheHits": 89
    }


@router.get("/cases")
async def list_cases(status: str | None = None, page: int = 0, size: int = 50):
    return {
        "items": [],
        "total": 0
    }


@router.get("/renewals/queue")
async def get_renewals_queue():
    return RENEWAL_QUEUE


@router.get("/renewals/dashboard")
async def get_renewals_dashboard(includeSimulated: bool = False):
    return {
        "renewals_due_30d": 1240,
        "premium_at_risk_inr": 38450000,
        "agent_contacted_count": 892,
        "conversion_rate": 78.4,
        "human_handoff_count": 94,
        "risk_bands": [
            {"band": "Low Risk", "count": 620, "premium": 18200000},
            {"band": "Medium Risk", "count": 410, "premium": 12450000},
            {"band": "High Risk", "count": 210, "premium": 7800000}
        ]
    }
