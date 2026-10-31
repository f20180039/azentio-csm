"""Core banking: the session customer's accounts and transactions."""
from typing import Annotated

from fastapi import APIRouter, Query

from app.enums import API_PREFIX, Route, TxnStatus
from app.guard import SessionDep, StoreDep

router = APIRouter(prefix=API_PREFIX, tags=["CBS"])

DEFAULT_TXN_LIMIT = 10
MAX_TXN_LIMIT = 100


@router.get(Route.CBS_ACCOUNTS)
def accounts(customer: SessionDep, store: StoreDep) -> dict:
    return {"items": store.get_accounts(customer["customer_ref"])}


@router.get(Route.CBS_TRANSACTIONS)
def transactions(customer: SessionDep, store: StoreDep, status: TxnStatus | None = None, ref: str | None = None,
                 limit: Annotated[int, Query(ge=1, le=MAX_TXN_LIMIT)] = DEFAULT_TXN_LIMIT) -> dict:
    return {"items": store.get_transactions(customer["customer_ref"], status, ref, limit)}
