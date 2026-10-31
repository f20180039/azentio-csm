"""Renewal Desk endpoints. Staff start calls and read; only the voice account runs the call's tools."""
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.auth import User, admin, staff, staff_or_voice, voice
from app.paths import ApiPath
from app.services.container import Services, services

router = APIRouter(prefix=ApiPath.RENEWALS, tags=["Renewals"])


class StartCallRequest(BaseModel):
    policyId: str | None = None
    simulated: bool | None = None


class MarkSimulatedRequest(BaseModel):
    callIds: list[UUID] | None = None


class VerifyRequest(BaseModel):
    dateOfBirth: str | None = None


class QuoteRequest(BaseModel):
    dropAddons: list[str] | None = None
    paymentPlan: str | None = None
    discountPercent: int | None = None


class PaymentLinkRequest(BaseModel):
    quoteId: UUID | None = None


class HandoffRequest(BaseModel):
    reason: str | None = None
    callbackAt: str | None = None


class TurnRequest(BaseModel):
    role: str | None = None
    text: str | None = None
    at: str | None = None


@router.get(ApiPath.RENEWAL_DASHBOARD)
def dashboard(includeSimulated: bool = False, _: User = Depends(staff), s: Services = Depends(services)):
    return s.dashboard.dashboard(includeSimulated)


@router.get(ApiPath.RENEWAL_QUEUE)
def queue(_: User = Depends(staff), s: Services = Depends(services)):
    return s.renewals.queue()


@router.post(ApiPath.RENEWAL_CALLS, status_code=201)
def start_call(body: StartCallRequest, user: User = Depends(staff), s: Services = Depends(services)):
    return s.renewals.start_call(body.policyId, bool(body.simulated), user.username)


@router.post(ApiPath.RENEWAL_MARK_SIMULATED)
def mark_simulated(body: MarkSimulatedRequest, user: User = Depends(admin), s: Services = Depends(services)):
    return {"marked": s.dashboard.mark_simulated([str(c) for c in body.callIds or []], user.username)}


@router.get(ApiPath.RENEWAL_CALL)
def get_call(call_id: UUID, _: User = Depends(staff_or_voice), s: Services = Depends(services)):
    return s.renewals.get_call(str(call_id))


@router.post(ApiPath.RENEWAL_VERIFY)
def verify(call_id: UUID, body: VerifyRequest, user: User = Depends(voice), s: Services = Depends(services)):
    return s.renewals.verify(str(call_id), body.dateOfBirth, user.username)


@router.get(ApiPath.RENEWAL_POLICY)
def policy(call_id: UUID, user: User = Depends(voice), s: Services = Depends(services)):
    return s.renewals.policy(str(call_id), user.username)


@router.get(ApiPath.RENEWAL_OPTIONS)
def options(call_id: UUID, user: User = Depends(voice), s: Services = Depends(services)):
    return s.renewals.options(str(call_id), user.username)


@router.post(ApiPath.RENEWAL_QUOTE)
def quote(call_id: UUID, body: QuoteRequest, user: User = Depends(voice), s: Services = Depends(services)):
    return s.renewals.quote(str(call_id), body.dropAddons, body.paymentPlan, body.discountPercent, user.username)


@router.post(ApiPath.RENEWAL_PAYMENT_LINK)
def payment_link(call_id: UUID, body: PaymentLinkRequest, user: User = Depends(voice),
                 s: Services = Depends(services)):
    return s.renewals.payment_link(str(call_id), str(body.quoteId) if body.quoteId else None, user.username)


@router.post(ApiPath.RENEWAL_HANDOFF)
def handoff(call_id: UUID, body: HandoffRequest, user: User = Depends(voice), s: Services = Depends(services)):
    return s.renewals.handoff(str(call_id), body.reason, body.callbackAt, user.username)


@router.post(ApiPath.RENEWAL_TURNS, status_code=204)
def turn(call_id: UUID, body: TurnRequest, user: User = Depends(voice), s: Services = Depends(services)):
    s.renewals.turn(str(call_id), body.role, body.text, body.at, user.username)
    return Response(status_code=204)


@router.post(ApiPath.RENEWAL_END)
def end(call_id: UUID, user: User = Depends(staff_or_voice), s: Services = Depends(services)):
    return s.renewals.end(str(call_id), user.username)
