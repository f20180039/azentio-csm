"""Loan management: the session customer's loan accounts and schedules."""
from fastapi import APIRouter

from app.enums import API_PREFIX, ProductType, Route
from app.guard import SessionDep, StoreDep, owns

router = APIRouter(prefix=API_PREFIX, tags=["LMS"])


@router.get(Route.LMS_LOANS)
def loans(customer: SessionDep, store: StoreDep, type: ProductType | None = None) -> dict:
    return {"items": store.get_loans(customer["customer_ref"], type)}


@router.get(Route.LMS_SCHEDULE)
def schedule(loan_id: str, customer: SessionDep, store: StoreDep) -> dict:
    owns(customer, store.get_loan(loan_id))
    return store.get_loan_schedule(loan_id)
