"""Caller verification, sessions, lockouts and the per-customer record guard."""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, Header

from app import store as store_module
from app.config import settings
from app.enums import (
    SESSION_HEADER,
    AuditAction,
    ErrorCode,
    EscalationCategory,
    EscalationReason,
    LockScope,
    VerifyMismatch,
    VerifyOutcome,
)
from app.errors import ApiError
from app.security.audit import audit_ledger
from app.store import BankStore

MOBILE_DIGITS = 10
COUNTRY_CODE = "91"
TRUNK_PREFIX = "0"

Customer = dict[str, Any]


def get_store() -> BankStore:
    return store_module.store


def get_now() -> datetime:
    return datetime.now(timezone.utc)


StoreDep = Annotated[BankStore, Depends(get_store)]
NowDep = Annotated[datetime, Depends(get_now)]


def normalise_mobile(raw: str) -> str:
    """Digits only, without a leading +91 / 91 or trunk 0."""
    d = "".join(c for c in str(raw) if c.isdigit())
    if len(d) == MOBILE_DIGITS + len(COUNTRY_CODE) and d.startswith(COUNTRY_CODE):
        return d[len(COUNTRY_CODE):]
    if len(d) == MOBILE_DIGITS + len(TRUNK_PREFIX) and d.startswith(TRUNK_PREFIX):
        return d[len(TRUNK_PREFIX):]
    return d


def normalise_dob(raw: str) -> str:
    try:
        return date.fromisoformat(str(raw).strip()).isoformat()
    except ValueError:
        return str(raw).strip()


def verify_caller(store: BankStore, now: datetime, mobile: str, dob: str, call_id: str,
                  caller_ref: str | None) -> dict[str, Any]:
    caller_key = (caller_ref or "").strip() or call_id
    mobile_n, dob_n = normalise_mobile(mobile), normalise_dob(dob)
    customer = next((c for c in store.customers.values() if c["mobile"] == mobile_n), None)
    customer_ref = customer["customer_ref"] if customer else None
    target_key = customer_ref or mobile_n

    def record(outcome: VerifyOutcome) -> None:
        store.record_verification_attempt(mobile_n, dob_n, call_id, outcome == VerifyOutcome.SUCCESS, now,
                                          outcome=outcome, customer_ref=customer_ref, caller_key=caller_key,
                                          target_key=target_key)
        audit_ledger.record(actor=f"call:{call_id}", action=AuditAction.VERIFY_ATTEMPT,
                            entity_ref=customer_ref or "UNKNOWN",
                            payload={"call_id": call_id, "caller_ref": caller_ref, "outcome": str(outcome)})

    if store.is_locked(LockScope.CALLER, caller_key, now):
        record(VerifyOutcome.CALLER_BLOCKED)
        raise caller_blocked()
    if store.is_locked(LockScope.CUSTOMER, target_key, now):
        record(VerifyOutcome.LOCKED)
        raise locked()

    if customer and customer["dob"] == dob_n:
        record(VerifyOutcome.SUCCESS)
        session = store.create_session(customer["customer_ref"], call_id, settings.session_ttl_seconds, now)
        return {"session": session["session"], "expires_in": settings.session_ttl_seconds,
                "customer": {"customer_ref": customer["customer_ref"], "first_name": customer["first_name"]}}

    record(VerifyOutcome.FAILED)
    customer_failures = store.count_target_failures(target_key, now - timedelta(minutes=settings.verify_window_minutes))
    if customer_failures >= settings.verify_max_failures:
        store.set_lock(LockScope.CUSTOMER, target_key, now + timedelta(minutes=settings.customer_lock_minutes))

    total, distinct = store.caller_failure_stats(caller_key, now - timedelta(minutes=settings.caller_window_minutes))
    if distinct >= settings.caller_max_distinct_customers or total >= settings.caller_max_failures:
        store.set_lock(LockScope.CALLER, caller_key, now + timedelta(minutes=settings.caller_block_minutes))
        store.create_escalation(reason=EscalationReason.CALLER_BLOCKED,
                                summary=f"Repeated failed verification across {distinct} customers",
                                call_id=call_id, category=EscalationCategory.SECURITY)
        raise caller_blocked()
    if customer_failures >= settings.verify_max_failures:
        raise locked()
    mismatch = VerifyMismatch.DOB_MISMATCH if customer else VerifyMismatch.MOBILE_NOT_FOUND
    raise ApiError(401, ErrorCode.VERIFICATION_FAILED, "Mobile number and date of birth do not match our records.",
                   attempts_left=settings.verify_max_failures - customer_failures, mismatch=mismatch)


def locked() -> ApiError:
    return ApiError(423, ErrorCode.LOCKED,
                    f"Verification is locked for {settings.customer_lock_minutes} minutes after repeated failures.")


def caller_blocked() -> ApiError:
    # attempts_left 0 lets clients that only know LOCKED / attempts_left stop retrying too.
    return ApiError(423, ErrorCode.CALLER_BLOCKED, "Too many failed verifications from this caller.", attempts_left=0)


def _session_customer(store: BankStore, now: datetime, token: str | None) -> Customer | None:
    if not token:
        return None
    session = store.get_session(token, now)
    return store.get_customer(session["customer_ref"]) if session else None


def require_session(store: StoreDep, now: NowDep,
                    x_customer_session: Annotated[str | None, Header(alias=SESSION_HEADER)] = None) -> Customer:
    customer = _session_customer(store, now, x_customer_session)
    if not customer:
        raise ApiError(401, ErrorCode.NOT_VERIFIED, "Verify the caller first; the session is missing or expired.")
    return customer


def optional_session(store: StoreDep, now: NowDep,
                     x_customer_session: Annotated[str | None, Header(alias=SESSION_HEADER)] = None) -> Customer | None:
    return _session_customer(store, now, x_customer_session)


SessionDep = Annotated[Customer, Depends(require_session)]
OptionalSessionDep = Annotated[Customer | None, Depends(optional_session)]


def owns(customer: Customer, record: dict[str, Any] | None) -> dict[str, Any]:
    """The record if it belongs to the session customer; 404 if missing, 403 NOT_YOUR_RECORD otherwise."""
    if record is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "No such record.")
    if record.get("customer_ref") != customer["customer_ref"]:
        raise ApiError(403, ErrorCode.NOT_YOUR_RECORD, "That record belongs to another customer.")
    return record
