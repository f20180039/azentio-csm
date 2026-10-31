"""Operations view (HTTP Basic): every record the agent raised, and a demo reset."""
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings
from app.enums import API_PREFIX, ErrorCode, RecordKind, Route
from app.errors import ApiError
from app.guard import StoreDep

basic = HTTPBasic(auto_error=False)


def require_ops(credentials: Annotated[HTTPBasicCredentials | None, Depends(basic)]) -> None:
    ok = credentials is not None and (
        secrets.compare_digest(credentials.username.encode(), settings.ops_username.encode())
        & secrets.compare_digest(credentials.password.encode(), settings.ops_password.encode())
    )
    if not ok:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "Operations endpoints need HTTP Basic credentials.")


router = APIRouter(prefix=API_PREFIX, tags=["Operations"], dependencies=[Depends(require_ops)])


@router.get(Route.OPS_RECORDS)
def records(store: StoreDep, kind: RecordKind | None = None) -> dict:
    return {"items": store.list_records(kind)}


@router.post(Route.OPS_RESET)
def reset(store: StoreDep) -> dict:
    store.reset()
    return {"reset": True}
