"""HTTP Basic authentication for Azentio-CSM System-of-Record API."""
import secrets
from dataclasses import dataclass
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials


security = HTTPBasic()


@dataclass
class User:
    username: str
    roles: list[str]


USERS = {
    "analyst": ("analyst", ["ANALYST"]),
    "reviewer": ("reviewer", ["REVIEWER", "ANALYST"]),
    "admin": ("admin", ["ADMIN", "REVIEWER", "ANALYST"]),
    "voice": ("voice", ["VOICE", "ANALYST"]),
}


def get_current_user(credentials: HTTPBasicCredentials = Depends(security)) -> User:
    user_record = USERS.get(credentials.username)
    if not user_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    expected_password, roles = user_record
    correct_password = secrets.compare_digest(
        credentials.password.encode("utf8"), expected_password.encode("utf8")
    )
    if not correct_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return User(username=credentials.username, roles=roles)
