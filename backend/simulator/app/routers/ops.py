"""Operations view (HTTP Basic): every record the agent raised, one customer's full profile, and a demo reset."""
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings
from app.enums import API_PREFIX, ErrorCode, RecordKind, Route
from app.errors import ApiError
from app.guard import StoreDep

basic = HTTPBasic(auto_error=False)


def require_ops(credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)]) -> None:
    ok = credentials is not None and (
        secrets.compare_digest(credentials.username.encode(), settings.ops_username.encode())
        & secrets.compare_digest(credentials.password.encode(), settings.ops_password.encode())
    )
    if not ok:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "Operations endpoints need HTTP Basic credentials.")


router = APIRouter(prefix=API_PREFIX, tags=["Operations"], dependencies=[Depends(require_ops)])


@router.get(Route.OPS_RECORDS)
def records(store: StoreDep, kind: RecordKind | None = None) -> dict:
    return {"items": store.list_records(kind)}


@router.get(Route.OPS_CUSTOMER)
def customer_profile(customer_ref: str, store: StoreDep) -> dict:
    """Everything the bank holds for one customer, seeded and raised in calls, for the operator panel's customer card."""
    customer = store.get_customer(customer_ref)
    if customer is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "No customer with that reference.")
    return {
        "customer": customer,
        "accounts": store.get_accounts(customer_ref),
        "loans": store.get_loans(customer_ref),
        "applications": store.get_applications(customer_ref),
        "transactions": store.get_transactions(customer_ref),
        "policies": store.get_policies(customer_ref),
        "claims": store.get_claims(customer_ref),
        "tickets": store.get_tickets(customer_ref),
        "complaints": store.get_complaints(customer_ref),
    }


@router.post(Route.OPS_RESET)
def reset(store: StoreDep) -> dict:
    store.reset()
    return {"reset": True}
