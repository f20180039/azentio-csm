"""Ops and Admin endpoints for System of Record."""
from fastapi import APIRouter, Depends
from app.auth import User, get_current_user
from app.store import store

router = APIRouter(tags=["Ops"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "api"}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "username": user.username,
        "roles": user.roles,
    }


@router.get("/packs")
def packs(user: User = Depends(get_current_user)):
    return [
        {
            "id": "demo",
            "label": "Demo documents",
            "extractionSchema": "demo",
            "routing": {"autoClearBelow": 0.2, "escalateAtOrAbove": 0.8},
            "rules": [
                {
                    "id": "CORE-DUPLICATE-DOC",
                    "weight": 0.5,
                    "rationale": "Same file already seen in another case",
                },
                {
                    "id": "CORE-HIDDEN-TEXT",
                    "weight": 0.6,
                    "rationale": "Text a human cannot see is a manipulation signal",
                },
                {
                    "id": "CORE-INJECTION",
                    "weight": 0.8,
                    "rationale": "Instructions aimed at the AI inside a document",
                },
            ],
        }
    ]


@router.get("/stats")
def stats(user: User = Depends(get_current_user)):
    return {
        "cases": 12,
        "accuracy": 0.94,
        "pending": 3,
        "resolved": 9,
    }


@router.get("/audit/verify")
def verify_audit(user: User = Depends(get_current_user)):
    return store.verify_audit()
