import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = ""
    stt_model: str = "whisper-large-v3-turbo"
    llm_model: str = "openai/gpt-oss-120b"
    api_base: str = "http://localhost:8080/api/v1"
    api_user: str = "voice"
    api_password: str = "voice"
    tts_voice: str = "en-IN-NeerjaNeural"


def load_settings(env_file: Path | None = None) -> Settings:
    os.environ.pop("ANTHROPIC_API_KEY", None)
    file_values = dotenv_values(env_file) if env_file else {}

    def get(key: str, default: str) -> str:
        return os.environ.get(key) or file_values.get(key) or default

    return Settings(
        groq_api_key=get("GROQ_API_KEY", ""),
        stt_model=get("VOICE_STT_MODEL", Settings.stt_model),
        llm_model=get("VOICE_LLM_MODEL", Settings.llm_model),
        api_base=get("RENEWALS_API_BASE", Settings.api_base),
        api_user=get("RENEWALS_API_USER", Settings.api_user),
        api_password=get("RENEWALS_API_PASSWORD", Settings.api_password),
        tts_voice=get("VOICE_TTS_VOICE", Settings.tts_voice),
    )
