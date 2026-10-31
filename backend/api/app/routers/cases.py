"""Cases (one per call): staff read, reviewers decide."""
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import User, reviewer, staff
from app.paths import ApiPath
from app.services.container import Services, services
from app.services.support import parse
from app.vocab import CaseStatus

router = APIRouter(prefix=ApiPath.CASES, tags=["Cases"])


class DecisionRequest(BaseModel):
    action: str | None = None
    reason: str | None = None


@router.get("")
def list_cases(status: str | None = None, caseType: str | None = None,
               dateFrom: str | None = None, dateTo: str | None = None,
               page: int = 0, size: int = 20,
               _: User = Depends(staff), s: Services = Depends(services)):
    parsed = parse(CaseStatus, "status", status) if status else None
    return s.cases.list(parsed, caseType, page, size, date_from=dateFrom, date_to=dateTo)


@router.get(ApiPath.CASE)
def get_case(case_id: UUID, _: User = Depends(staff), s: Services = Depends(services)):
    return s.cases.get(str(case_id))


@router.post(ApiPath.CASE_DECISION)
def decide(case_id: UUID, body: DecisionRequest, user: User = Depends(reviewer), s: Services = Depends(services)):
    return s.cases.decide(str(case_id), body.action, body.reason, user.username)


@router.get(ApiPath.CASE_AUDIT)
def audit(case_id: UUID, _: User = Depends(staff), s: Services = Depends(services)):
    return s.cases.audit_for(str(case_id))
