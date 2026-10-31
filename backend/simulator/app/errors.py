"""Contract error shape: {"error": CODE, "detail": str, ...extra}."""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.enums import ErrorCode


class ApiError(Exception):
    def __init__(self, status: int, code: ErrorCode, detail: str = "", **extra: Any):
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status,
                            content={"error": str(exc.code), "detail": exc.detail, **exc.extra})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        return JSONResponse(status_code=422, content={"error": str(ErrorCode.VALIDATION_ERROR), "detail": problems})
