"""Support Call and Turn recording endpoints."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import User, get_current_user
from app.store import store

router = APIRouter(prefix="/support/calls", tags=["Support Calls"])


class StartCallRequest(BaseModel):
    channel: str = Field(default="VOICE")


class AddTurnRequest(BaseModel):
    role: str
    text: str
    at: str
    meta: dict[str, Any] = Field(default_factory=dict)


class EndCallRequest(BaseModel):
    outcome: str


@router.post("", status_code=status.HTTP_201_CREATED)
def start_call(body: StartCallRequest, user: User = Depends(get_current_user)):
    cid = store.start_support_call(body.channel)
    return {"id": cid}


@router.post("/{call_id}/turns", status_code=status.HTTP_201_CREATED)
def add_turn(call_id: str, body: AddTurnRequest, user: User = Depends(get_current_user)):
    seq = store.add_support_turn(call_id, body.role, body.text, body.at, body.meta)
    return {"seq": seq}


@router.patch("/{call_id}/turns/{seq}/meta")
def patch_turn_meta(
    call_id: str,
    seq: int,
    meta: dict[str, Any],
    user: User = Depends(get_current_user),
):
    ok = store.patch_support_meta(call_id, seq, meta)
    if not ok:
        raise HTTPException(status_code=404, detail="Turn not found")
    return {"ok": True}


@router.post("/{call_id}/end")
def end_call(call_id: str, body: EndCallRequest, user: User = Depends(get_current_user)):
    ok = store.end_support_call(call_id, body.outcome)
    if not ok:
        raise HTTPException(status_code=404, detail="Call not found")
    return {"ok": True}


@router.get("/{call_id}")
def get_call(call_id: str, user: User = Depends(get_current_user)):
    call = store.get_support_call(call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


@router.get("")
def list_calls(
    outcome: str | None = None,
    limit: int = 50,
    user: User = Depends(get_current_user),
):
    items = store.list_support_calls(outcome=outcome, limit=limit)
    return {"items": items}
