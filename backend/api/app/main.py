"""Azentio-CSM system-of-record API: renewal calls, support call records, cases and the audit chain."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import errors
from app.clock import Clock
from app.config import Settings
from app.paths import API_PREFIX, ApiPath
from app.routers import cases, ops, renewals, review, support
from app.services.container import build


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Azentio-CSM System of Record API",
        version="1.0.0",
        docs_url="/swagger-ui.html",
        openapi_url="/v3/api-docs",
    )
    # Schema and seed are applied here, so the database is ready before the first request.
    app.state.services = build(settings, clock)
    errors.install(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Cache", "Retry-After", "Location"],
    )
    for r in (ops.router, support.router, review.router, renewals.router, cases.router):
        app.include_router(r, prefix=API_PREFIX)

    @app.get(ApiPath.HEALTH, tags=["Health"])
    def root_health():
        return {"status": "ok", "service": "api"}

    return app


app = create_app()
