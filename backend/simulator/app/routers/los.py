"""Loan origination: the session customer's applications."""
from fastapi import APIRouter

from app.enums import API_PREFIX, Route
from app.guard import SessionDep, StoreDep

router = APIRouter(prefix=API_PREFIX, tags=["LOS"])


@router.get(Route.LOS_APPLICATIONS)
def applications(customer: SessionDep, store: StoreDep) -> dict:
    return {"items": store.get_applications(customer["customer_ref"])}
