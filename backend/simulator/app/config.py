"""Configuration settings for Azentio-CSM Core API."""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Bank Simulator"
    environment: str = "development"
    debug: bool = False
    
    # Network & Ports
    host: str = "0.0.0.0"
    port: int = 8090
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]
    cors_headers: list[str] = ["Authorization", "Content-Type", "Accept", "X-Customer-Session"]

    # Customer verification
    session_ttl_seconds: int = 900
    verify_max_failures: int = 3
    verify_window_minutes: int = 15
    customer_lock_minutes: int = 15

    # Per-caller brute-force protection (caller_ref, else call_id)
    caller_window_minutes: int = 30
    caller_max_distinct_customers: int = 3
    caller_max_failures: int = 6
    caller_block_minutes: int = 30

    ticket_eta_days: int = 2

    ops_username: str = "ops"
    ops_password: str = "ops"

    # Internal microservices
    voice_url: str = os.getenv("VOICE_URL", "http://localhost:7861")
    
    # Security & Auth
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "bfsi-super-secure-jwt-secret-key-2026")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 8  # 8 hours
    
    # Compliance & Calling Hours
    enforce_calling_hours: bool = False
    data_localization_region: str = "IN-MUMBAI-1"
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
