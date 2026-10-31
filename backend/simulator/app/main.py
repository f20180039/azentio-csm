"""Bank Simulator API."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.errors import install_error_handlers
from app.routers import audit, auth, cbs, insurance, lms, los, verify


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=settings.cors_headers,
)
install_error_handlers(app)

app.include_router(auth.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
for module in (verify, los, lms, cbs, insurance):
    app.include_router(module.router)


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "service": "bank-simulator"
    }
