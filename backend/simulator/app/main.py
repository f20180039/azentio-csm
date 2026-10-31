"""Bank Simulator API."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import audit, auth, cbs


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.security.audit import audit_ledger
    audit_ledger.record(actor="SYSTEM", action="SYSTEM_BOOT", entity_ref="ENGINE", payload={"version": "1.0.0"})
    yield


app = FastAPI(
    title="Bank Simulator API",
    description="Mock banking, lending, and insurance simulator for the CSM voice agent.",
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
app.include_router(auth.router, prefix="/api")
app.include_router(cbs.router, prefix="/api")
app.include_router(audit.router, prefix="/api")


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "service": "bank-simulator"
    }
