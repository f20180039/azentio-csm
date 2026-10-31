"""Support call records (shared contract). Only the voice account writes; staff and voice read."""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from app.auth import User, staff_or_voice, voice
from app.paths import ApiPath
from app.services.container import Services, services
from app.services.support import parse
from app.vocab import Channel, Outcome, TurnRole

router = APIRouter(prefix=ApiPath.SUPPORT_CALLS, tags=["Support Calls"])


class StartRequest(BaseModel):
    channel: str | None = None


class TurnRequest(BaseModel):
    role: str | None = None
    text: str | None = None
    at: str | None = None
    meta: Any = None


class EndRequest(BaseModel):
    outcome: str | None = None


@router.post("", status_code=201)
def start(body: StartRequest | None = None, user: User = Depends(voice), s: Services = Depends(services)):
    return s.support.start(parse(Channel, "channel", body.channel if body else None), user.username)


@router.post(ApiPath.SUPPORT_TURNS, status_code=201)
def add_turn(call_id: UUID, body: TurnRequest, _: User = Depends(voice), s: Services = Depends(services)):
    role = parse(TurnRole, "role", body.role)
    return s.support.add_turn(str(call_id), role, body.text, body.at, body.meta)


@router.patch(ApiPath.SUPPORT_TURN_META)
def patch_meta(call_id: UUID, seq: int, patch: Any = Body(None), _: User = Depends(voice),
               s: Services = Depends(services)):
    return s.support.patch_meta(str(call_id), seq, patch)


@router.post(ApiPath.SUPPORT_END)
def end(call_id: UUID, body: EndRequest | None = None, user: User = Depends(voice), s: Services = Depends(services)):
    return s.support.end(str(call_id), parse(Outcome, "outcome", body.outcome if body else None), user.username)


@router.get(ApiPath.SUPPORT_CALL)
def get_call(call_id: UUID, _: User = Depends(staff_or_voice), s: Services = Depends(services)):
    return s.support.get(str(call_id))


@router.get("")
def list_calls(outcome: str | None = None, limit: int = 50, _: User = Depends(staff_or_voice),
               s: Services = Depends(services)):
    parsed = parse(Outcome, "outcome", outcome) if outcome and outcome.strip() else None
    return s.support.list(parsed, limit)
