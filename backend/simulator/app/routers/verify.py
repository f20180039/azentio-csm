"""POST /v1/verify: mobile + date of birth gives a customer session."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.enums import API_PREFIX, Route
from app.guard import NowDep, StoreDep, verify_caller

router = APIRouter(prefix=API_PREFIX, tags=["Verification"])


class VerifyRequest(BaseModel):
    mobile: str = Field(min_length=1)
    dob: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    caller_ref: str | None = None


@router.post(Route.VERIFY)
def verify(body: VerifyRequest, store: StoreDep, now: NowDep) -> dict:
    return verify_caller(store, now, body.mobile, body.dob, body.call_id, body.caller_ref)
