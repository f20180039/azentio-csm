"""Configuration settings for Azentio-CSM Core API."""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Azentio-CSM Core API"
    environment: str = "development"
    debug: bool = False
    
    # Network & Ports
    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000", "*"]
    
    # Internal microservices
    agent_url: str = os.getenv("AGENT_URL", "http://localhost:8000")
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
