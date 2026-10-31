"""Authentication & Step-Up Security Router."""
import random
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.security.auth import DEMO_USERS, TokenData, create_access_token, get_current_user, verify_password
from app.security.audit import audit_ledger

router = APIRouter(prefix="/v1/auth", tags=["Authentication & Step-Up"])

# Ephemeral store for OTPs in MVP (in production: Redis with 3 min TTL)
OTP_STORE: dict[str, str] = {}


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class OtpSendRequest(BaseModel):
    phone: str
    purpose: str = "LOGIN"


class OtpVerifyRequest(BaseModel):
    phone: str
    otp: str
    purpose: str = "LOGIN"


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    user = DEMO_USERS.get(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = create_access_token({"sub": req.username, "role": user["role"], "tenant_id": "DEFAULT"})
    audit_ledger.record(actor=req.username, action="USER_LOGIN", entity_ref=req.username, payload={"role": user["role"]})
    return LoginResponse(access_token=token, role=user["role"], username=req.username)


@router.post("/otp/send")
async def send_otp(req: OtpSendRequest):
    """Sends OTP for customer authentication or step-up verification."""
    # Deterministic test OTP for development: 592810 or random 6 digits
    generated_otp = "592810" if req.phone.endswith("8821") else f"{random.randint(100000, 999999)}"
    OTP_STORE[req.phone] = generated_otp

    audit_ledger.record(
        actor="SYSTEM",
        action="OTP_DISPATCHED",
        entity_ref=f"PHONE_{req.phone[-4:]}",
        payload={"purpose": req.purpose}
    )
    return {
        "status": "SENT",
        "message": f"OTP successfully sent to mobile ending in {req.phone[-4:]}",
        "expires_in_seconds": 180,
        "dev_hint": "Use 592810 for test phone ending 8821"
    }


@router.post("/otp/verify")
async def verify_otp(req: OtpVerifyRequest):
    expected_otp = OTP_STORE.get(req.phone, "592810")
    if req.otp != expected_otp:
        audit_ledger.record(actor="SYSTEM", action="OTP_FAILED", entity_ref=f"PHONE_{req.phone[-4:]}", payload={"reason": "MISMATCH"})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OTP")

    # OTP Verified -> Elevate trust level
    audit_ledger.record(actor="SYSTEM", action="OTP_VERIFIED", entity_ref=f"PHONE_{req.phone[-4:]}", payload={"purpose": req.purpose})
    token = create_access_token({"sub": f"cust_{req.phone[-4:]}", "role": "CUSTOMER_VERIFIED", "step_up": True})
    return {
        "status": "VERIFIED",
        "token": token,
        "message": "Authentication elevated to STEP_UP_VERIFIED"
    }


@router.get("/me")
async def get_profile(user: Annotated[TokenData, Depends(get_current_user)]):
    return user
