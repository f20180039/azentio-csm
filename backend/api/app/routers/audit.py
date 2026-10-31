"""Cryptographic Audit Chain Router."""
from fastapi import APIRouter
from app.security.audit import audit_ledger

router = APIRouter(prefix="/v1/audit", tags=["Audit & Regulatory Compliance"])


@router.get("/entries")
async def get_audit_entries(limit: int = 50):
    """Retrieve recent append-only audit events."""
    return {"entries": audit_ledger.get_entries(limit=limit)}


@router.get("/verify")
async def verify_chain():
    """Validates that no historical audit record or hash has been tampered with."""
    is_valid, broken_idx = audit_ledger.verify_integrity()
    return {
        "status": "VALID" if is_valid else "CORRUPTED",
        "tamper_evident": True,
        "algorithm": "SHA-256",
        "verified_blocks": len(audit_ledger.get_entries(limit=1000)),
        "broken_block_index": broken_idx
    }
