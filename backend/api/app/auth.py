"""HTTP Basic users and role checks, matching the Java SecurityConfig (voice holds only VOICE)."""
import secrets
from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.errors import ApiError
from app.vocab import Role

# auto_error=False: no WWW-Authenticate header, so browsers don't pop their native login dialog.
security = HTTPBasic(auto_error=False)


@dataclass(frozen=True)
class User:
    username: str
    roles: frozenset[Role]

    def has_any(self, *roles: Role) -> bool:
        return any(r in self.roles for r in roles)


USERS: dict[str, tuple[str, frozenset[Role]]] = {
    "analyst": ("analyst", frozenset({Role.ANALYST})),
    "reviewer": ("reviewer", frozenset({Role.REVIEWER, Role.ANALYST})),
    "admin": ("admin", frozenset({Role.ADMIN, Role.REVIEWER, Role.ANALYST})),
    "voice": ("voice", frozenset({Role.VOICE})),
}


def get_current_user(credentials: HTTPBasicCredentials | None = Depends(security)) -> User:
    if credentials is None:
        raise ApiError.unauthorized()
    record = USERS.get(credentials.username)
    if record is None:
        raise ApiError.unauthorized()
    password, roles = record
    if not secrets.compare_digest(credentials.password.encode(), password.encode()):
        raise ApiError.unauthorized()
    return User(credentials.username, roles)


def require(*roles: Role):
    """Dependency: the signed-in user must hold at least one of `roles`."""

    def dep(user: User = Depends(get_current_user)) -> User:
        if not user.has_any(*roles):
            raise ApiError.forbidden("Your role does not allow this action.")
        return user

    return dep


staff = require(Role.ANALYST)
reviewer = require(Role.REVIEWER)
admin = require(Role.ADMIN)
voice = require(Role.VOICE)
staff_or_voice = require(Role.ANALYST, Role.VOICE)
