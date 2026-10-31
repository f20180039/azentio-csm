"""Azentio-CSM - Enterprise BFSI Conversational AI Platform Core API."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import analytics, audit, auth, caseintel, cbs, chat, flows


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Seed initial genesis block in audit ledger
    from app.security.audit import audit_ledger
    audit_ledger.record(actor="SYSTEM", action="SYSTEM_BOOT", entity_ref="ENGINE", payload={"version": "1.0.0"})
    yield
    # Teardown logic if needed


app = FastAPI(
    title="Azentio-CSM - BFSI Conversational AI Platform API",
    description="Enterprise Conversational AI suite for Banking, Lending, Insurance & Wealth.",
    version="1.0.0",
    docs_url="/swagger-ui.html",
    openapi_url="/v1/openapi.json",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Modular Routers
app.include_router(caseintel.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(cbs.router, prefix="/api")
app.include_router(flows.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(audit.router, prefix="/api")


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "UP",
        "service": "Azentio-CSM Core API (FastAPI)",
        "region": settings.data_localization_region,
        "compliance": ["RBI-Outsourcing", "DPDP-Act-2023", "PCI-DSS-Ready"]
    }
