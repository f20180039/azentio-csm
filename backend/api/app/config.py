"""Configuration for the system-of-record API, read from the environment."""
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RESOURCES = Path(__file__).resolve().parent / "resources"
DEFAULT_DB_PATH = BASE_DIR / "data" / "runtime" / "api.db"
DEFAULT_PLAYBOOK = RESOURCES / "playbooks" / "health-renewal.yml"
TIMEZONE = "Asia/Kolkata"

_TRUE = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None or raw.strip() == "" else raw.strip().lower() in _TRUE


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    return default if not raw else [s.strip() for s in raw.split(",") if s.strip()]


@dataclass
class Settings:
    db_path: str = str(DEFAULT_DB_PATH)
    enforce_calling_hours: bool = True
    playbook_path: str = str(DEFAULT_PLAYBOOK)
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.getenv("API_DB_PATH") or str(DEFAULT_DB_PATH),
            enforce_calling_hours=_env_bool("ENFORCE_CALLING_HOURS", True),
            playbook_path=os.getenv("RENEWAL_PLAYBOOK") or str(DEFAULT_PLAYBOOK),
            cors_origins=_env_list("CORS_ORIGINS", ["http://localhost:5173"]),
        )
