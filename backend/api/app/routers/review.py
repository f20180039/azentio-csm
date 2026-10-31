"""Review queue, lessons and insights (shared contract, 31 Oct). Ratings and turn feedback live on the call router."""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import User, admin, reviewer, staff, staff_or_voice
from app.paths import ApiPath
from app.services.container import Services, services
from app.services.support import parse
from app.vocab import LessonStatus

router = APIRouter(prefix=ApiPath.SUPPORT, tags=["Support Review"])


class ResolveRequest(BaseModel):
    note: Any = None


class LessonRequest(BaseModel):
    text: Any = None
    sourceCallId: Any = None
    sourceSeq: Any = None


class LessonPatch(BaseModel):
    status: str | None = None


@router.get(ApiPath.SUPPORT_REVIEW)
def review_queue(limit: int = 50, _: User = Depends(staff), s: Services = Depends(services)):
    return s.review.queue(limit)


@router.post(ApiPath.SUPPORT_REVIEW_RESOLVE)
def resolve(call_id: UUID, body: ResolveRequest, user: User = Depends(reviewer), s: Services = Depends(services)):
    return s.review.resolve(str(call_id), body.note, user)


@router.get(ApiPath.SUPPORT_LESSONS)
def lessons(active: bool | None = None, _: User = Depends(staff_or_voice), s: Services = Depends(services)):
    return s.review.lessons(active)


@router.post(ApiPath.SUPPORT_LESSONS, status_code=201)
def propose(body: LessonRequest, user: User = Depends(reviewer), s: Services = Depends(services)):
    return s.review.propose(body.text, body.sourceCallId, body.sourceSeq, user)


@router.patch(ApiPath.SUPPORT_LESSON)
def set_status(lesson_id: str, body: LessonPatch, user: User = Depends(admin), s: Services = Depends(services)):
    return s.review.set_status(lesson_id, parse(LessonStatus, "status", body.status), user)


@router.get(ApiPath.SUPPORT_INSIGHTS)
def insights(_: User = Depends(staff), s: Services = Depends(services)):
    return s.review.insights()
