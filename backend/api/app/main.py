"""Azentio-CSM System-of-Record Core API."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import cases, ops, renewals, support
from app.store import store


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.record_audit(
        actor="SYSTEM",
        action="API_BOOT",
        entity_ref="SYSTEM_OF_RECORD",
        payload={"version": "1.0.0", "db": "sqlite"},
    )
    yield


app = FastAPI(
    title="Azentio-CSM System of Record API",
    description="FastAPI implementation of Azentio-CSM System of Record (Support calls, Renewals, Cases).",
    version="1.0.0",
    docs_url="/swagger-ui.html",
    openapi_url="/v1/openapi.json",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers under /api/v1
app.include_router(ops.router, prefix="/api/v1")
app.include_router(support.router, prefix="/api/v1")
app.include_router(renewals.router, prefix="/api/v1")
app.include_router(cases.router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
async def root_health():
    return {"status": "ok", "service": "api"}
