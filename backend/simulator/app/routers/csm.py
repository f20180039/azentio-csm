"""CSM platform: service requests, complaints, routed queries and escalations."""
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.config import settings
from app.enums import API_PREFIX, ComplaintCategory, Route, Severity, TicketCategory
from app.guard import OptionalSessionDep, SessionDep, StoreDep, owns

router = APIRouter(prefix=API_PREFIX, tags=["CSM"])

TICKET_FIELDS = ("ref", "category", "status", "summary", "details", "created_on", "updated_on")
COMPLAINT_FIELDS = ("ref", "category", "severity", "status", "description", "escalated", "created_at")


class TicketRequest(BaseModel):
    category: TicketCategory
    summary: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    call_id: str = Field(min_length=1)


class ComplaintRequest(BaseModel):
    category: ComplaintCategory
    description: str = Field(min_length=1)
    severity: Severity
    call_id: str = Field(min_length=1)


class RoutedRequest(BaseModel):
    query_text: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    customer_ref: str | None = None


class EscalationRequest(BaseModel):
    reason: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    call_id: str = Field(min_length=1)


def _ticket_view(ticket: dict[str, Any]) -> dict[str, Any]:
    """details carries what the request is about (e.g. loan_id), so a caller can go from a request to its loan."""
    return {k: ticket.get(k, {} if k == "details" else None) for k in TICKET_FIELDS}


@router.get(Route.CSM_TICKETS)
def tickets(customer: SessionDep, store: StoreDep) -> dict:
    return {"items": [_ticket_view(t) for t in store.get_tickets(customer["customer_ref"])]}


@router.get(Route.CSM_TICKET)
def ticket(ref: str, customer: SessionDep, store: StoreDep) -> dict:
    return _ticket_view(owns(customer, store.get_ticket(ref)))


@router.post(Route.CSM_TICKETS, status_code=status.HTTP_201_CREATED)
def create_ticket(body: TicketRequest, customer: SessionDep, store: StoreDep) -> dict:
    return store.create_ticket(customer["customer_ref"], body.category, body.summary, body.details, body.call_id,
                               eta_days=settings.ticket_eta_days)


@router.get(Route.CSM_COMPLAINT)
def complaint(ref: str, customer: SessionDep, store: StoreDep) -> dict:
    c = owns(customer, store.get_complaint(ref))
    return {k: c.get(k) for k in COMPLAINT_FIELDS}


@router.post(Route.CSM_COMPLAINTS, status_code=status.HTTP_201_CREATED)
def create_complaint(body: ComplaintRequest, customer: SessionDep, store: StoreDep) -> dict:
    return store.create_complaint(customer["customer_ref"], body.category, body.description, body.severity, body.call_id)


@router.post(Route.CSM_ROUTED, status_code=status.HTTP_201_CREATED)
def create_routed(body: RoutedRequest, store: StoreDep) -> dict:
    return store.create_routed(body.query_text, body.reason, body.call_id, body.customer_ref)


@router.post(Route.CSM_ESCALATIONS, status_code=status.HTTP_201_CREATED)
def create_escalation(body: EscalationRequest, customer: OptionalSessionDep, store: StoreDep) -> dict:
    return store.create_escalation(body.reason, body.summary, body.call_id,
                                   customer_ref=customer["customer_ref"] if customer else None)
