"""CSM platform: service requests, complaints, routed queries and escalations."""
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.config import settings
from app.enums import API_PREFIX, ComplaintCategory, EscalationCategory, Route, Severity, TicketCategory
from app.guard import OptionalSessionDep, SessionDep, StoreDep, owns

router = APIRouter(prefix=API_PREFIX, tags=["CSM"])

TICKET_FIELDS = ("ref", "category", "status", "summary", "department", "progress", "eta_days", "created_on", "updated_on")


class TicketRequest(BaseModel):
    category: TicketCategory
    summary: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    call_id: str = Field(min_length=1)


class ComplaintRequest(BaseModel):
    category: ComplaintCategory
    description: str = Field(min_length=1)  # the structured summary
    severity: Severity
    call_id: str = Field(min_length=1)
    original_statement: str | None = None  # the caller's own words
    related_ref: str | None = None  # the account, loan or transaction reference it is about


class RoutedRequest(BaseModel):
    query_text: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    customer_ref: str | None = None


class EscalationRequest(BaseModel):
    reason: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    category: EscalationCategory | None = None
    related_refs: list[str] = Field(default_factory=list)  # tickets, complaints or other records it concerns


def ticket_view(ticket: dict[str, Any]) -> dict[str, Any]:
    """The ticket as the caller (and the ops status update) sees it: no details, call id or customer ref."""
    return {k: ticket[k] for k in TICKET_FIELDS}


@router.get(Route.CSM_TICKETS)
def tickets(customer: SessionDep, store: StoreDep) -> dict:
    return {"items": [ticket_view(t) for t in store.get_tickets(customer["customer_ref"])]}


@router.get(Route.CSM_TICKET)
def ticket(ref: str, customer: SessionDep, store: StoreDep) -> dict:
    return ticket_view(owns(customer, store.get_ticket(ref)))


@router.post(Route.CSM_TICKETS, status_code=status.HTTP_201_CREATED)
def create_ticket(body: TicketRequest, customer: SessionDep, store: StoreDep) -> dict:
    return store.create_ticket(customer["customer_ref"], body.category, body.summary, body.details, body.call_id,
                               eta_days=settings.ticket_eta_days)


@router.post(Route.CSM_COMPLAINTS, status_code=status.HTTP_201_CREATED)
def create_complaint(body: ComplaintRequest, customer: SessionDep, store: StoreDep) -> dict:
    return store.create_complaint(customer["customer_ref"], body.category, body.description, body.severity, body.call_id,
                                  original_statement=body.original_statement, related_ref=body.related_ref)


@router.post(Route.CSM_ROUTED, status_code=status.HTTP_201_CREATED)
def create_routed(body: RoutedRequest, store: StoreDep) -> dict:
    return store.create_routed(body.query_text, body.reason, body.call_id, body.customer_ref)


@router.post(Route.CSM_ESCALATIONS, status_code=status.HTTP_201_CREATED)
def create_escalation(body: EscalationRequest, customer: OptionalSessionDep, store: StoreDep) -> dict:
    return store.create_escalation(body.reason, body.summary, body.call_id,
                                   customer_ref=customer["customer_ref"] if customer else None,
                                   category=body.category, related_refs=body.related_refs)
