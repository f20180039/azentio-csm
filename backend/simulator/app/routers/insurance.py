"""Insurance: the session customer's policies and claims."""
from fastapi import APIRouter

from app.enums import API_PREFIX, Route
from app.guard import SessionDep, StoreDep

router = APIRouter(prefix=API_PREFIX, tags=["Insurance"])


@router.get(Route.INSURANCE_POLICIES)
def policies(customer: SessionDep, store: StoreDep) -> dict:
    return {"items": store.get_policies(customer["customer_ref"])}


@router.get(Route.INSURANCE_CLAIMS)
def claims(customer: SessionDep, store: StoreDep) -> dict:
    return {"items": store.get_claims(customer["customer_ref"])}
