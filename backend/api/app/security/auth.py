"""Authentication and RBAC security utilities."""
import base64
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from app.config import settings

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password[:72].encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password[:72].encode("utf-8"), hashed_password.encode("utf-8"))


class TokenData(BaseModel):
    username: str
    role: str
    tenant_id: str = "DEFAULT"


# Pre-configured demo accounts for BFSI testing
DEMO_USERS = {
    "analyst": {"password_hash": hash_password("analyst"), "role": "ANALYST"},
    "reviewer": {"password_hash": hash_password("reviewer"), "role": "REVIEWER"},
    "admin": {"password_hash": hash_password("admin"), "role": "ADMIN"},
    "voice": {"password_hash": hash_password("voice"), "role": "VOICE"},
}


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def get_current_user(request: Request) -> TokenData:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return TokenData(username="anonymous", role="GUEST")

    # 1. Handle HTTP Basic Auth (used by frontend client.ts)
    if auth_header.startswith("Basic "):
        try:
            b64_creds = auth_header[6:].strip()
            decoded = base64.b64decode(b64_creds).decode("utf-8")
            username, password = decoded.split(":", 1)
            user = DEMO_USERS.get(username)
            if not user or not verify_password(password, user["password_hash"]):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
            return TokenData(username=username, role=user["role"], tenant_id="DEFAULT")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Basic auth header")

    # 2. Handle Bearer JWT
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
            username: str = payload.get("sub")
            role: str = payload.get("role", "ANALYST")
            tenant_id: str = payload.get("tenant_id", "DEFAULT")
            if username is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
            return TokenData(username=username, role=role, tenant_id=tenant_id)
        except JWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token or expired session")

    return TokenData(username="anonymous", role="GUEST")
