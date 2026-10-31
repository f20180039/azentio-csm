"""Problem+json errors. The `detail` carries the refusal code the voice agent branches on."""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class ApiError(Exception):
    def __init__(self, status: int, title: str, detail: str):
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail

    @classmethod
    def not_found(cls, detail: str) -> "ApiError":
        return cls(404, "Not found", detail)

    @classmethod
    def bad_request(cls, detail: str) -> "ApiError":
        return cls(400, "Bad request", detail)

    @classmethod
    def conflict(cls, detail: str) -> "ApiError":
        return cls(409, "Conflict", detail)

    @classmethod
    def forbidden(cls, detail: str) -> "ApiError":
        return cls(403, "Forbidden", detail)

    @classmethod
    def unauthorized(cls) -> "ApiError":
        return cls(401, "Unauthorized", "Sign in with a valid username and password.")

    @classmethod
    def invalid_option(cls, code: str) -> "ApiError":
        return cls(422, "Request not allowed", code)


def problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status, "detail": detail},
        status_code=status,
        media_type=PROBLEM_JSON,
    )


def _validation_detail(e: RequestValidationError) -> str:
    parts = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
        parts.append(f"{loc or 'body'}: {err.get('msg')}")
    return "; ".join(parts) or "Invalid request"


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        return problem(e.status, e.title, e.detail)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, e: RequestValidationError):
        # A string detail, never a list: the voice client looks the detail up in a set.
        return problem(400, "Bad request", _validation_detail(e))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        return problem(e.status_code, "Error", str(e.detail))
