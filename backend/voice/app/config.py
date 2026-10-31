import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from .llm_chain import Link, default_chain_spec, parse_chain


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = ""
    stt_model: str = "whisper-large-v3-turbo"
    llm_chain: tuple[Link, ...] = ()
    api_base: str = "http://localhost:8080/api/v1"
    api_user: str = "voice"
    api_password: str = "voice"
    simulator_base: str = "http://localhost:8090/v1"
    tts_voice: str = "en-IN-NeerjaNeural"
    twilio_account_sid: str = ""
    twilio_auth_token: str = field(default="", repr=False)
    twilio_from: str = ""
    twilio_allowed_to: tuple[str, ...] = ()
    public_base_url: str = ""


def load_settings(env_file: Path | None = None) -> Settings:
    os.environ.pop("ANTHROPIC_API_KEY", None)
    file_values = dotenv_values(env_file) if env_file else {}

    def get(key: str, default: str) -> str:
        return os.environ.get(key) or file_values.get(key) or default

    keys = {"groq": get("GROQ_API_KEY", ""), "gemini": get("GEMINI_API_KEY", ""), "mistral": get("MISTRAL_API_KEY", "")}
    spec = get("VOICE_LLM_CHAIN", default_chain_spec(get("GEMINI_MODEL", ""), get("MISTRAL_MODEL", "")))
    return Settings(
        groq_api_key=keys["groq"],
        stt_model=get("VOICE_STT_MODEL", Settings.stt_model),
        llm_chain=parse_chain(spec, keys),
        api_base=get("RENEWALS_API_BASE", Settings.api_base),
        api_user=get("RENEWALS_API_USER", Settings.api_user),
        api_password=get("RENEWALS_API_PASSWORD", Settings.api_password),
        simulator_base=get("SIMULATOR_BASE", Settings.simulator_base),
        tts_voice=get("VOICE_TTS_VOICE", Settings.tts_voice),
        twilio_account_sid=get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=get("TWILIO_AUTH_TOKEN", ""),
        twilio_from=get("TWILIO_FROM", "").replace(" ", ""),
        twilio_allowed_to=tuple(n.replace(" ", "") for n in get("TWILIO_ALLOWED_TO", "").split(",") if n.strip()),
        public_base_url=get("PUBLIC_BASE_URL", "").rstrip("/"),
    )
