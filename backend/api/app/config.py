"""Configuration for Azentio-CSM System-of-Record API."""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "api.db"


class Settings(BaseSettings):
    app_name: str = "Azentio-CSM System of Record API"
    environment: str = "development"
    debug: bool = False
    port: int = 8080
    host: str = "0.0.0.0"

    db_path: str = os.getenv("API_DB_PATH", str(DEFAULT_DB_PATH))
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "*",
    ]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
