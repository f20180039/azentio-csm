import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from loguru import logger

from .llm_chain import Link, default_chain_spec, parse_chain
from .vocab import SpeechLanguage

PROXY_TOKEN_MIN_CHARS = 32  # a shorter VOICE_PROXY_TOKEN is ignored: the tunnel guard then behaves as if none were set


def parse_languages(spec: str) -> tuple[SpeechLanguage, ...]:
    """'en,kn' → (ENGLISH, KANNADA), 'en,kn,hi' adds HINDI; an unknown code is a ValueError at start-up, not a silent English-only call."""
    langs = tuple(dict.fromkeys(SpeechLanguage(p.strip().lower()) for p in spec.split(",") if p.strip()))
    return langs or (SpeechLanguage.ENGLISH,)


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = ""
    stt_model: str = "whisper-large-v3-turbo"
    llm_chain: tuple[Link, ...] = ()
    intent_model: str = "openai/gpt-oss-20b"
    translate_model: str = "openai/gpt-oss-20b"  # Groq model that puts Kannada and Hindi turns into English for the record
    api_base: str = "http://localhost:8080/api/v1"
    api_user: str = "voice"
    api_password: str = "voice"
    simulator_base: str = "http://localhost:8090/v1"
    human_agent_number: str = ""  # E.164 number a phone call is transferred to on escalation
    helpline_number: str = "1800 210 4455"  # spoken to browser callers (synthetic)
    tts_voice: str = "en-IN-NeerjaNeural"
    voice_languages: tuple[SpeechLanguage, ...] = (SpeechLanguage.ENGLISH,)
    twilio_account_sid: str = ""
    twilio_auth_token: str = field(default="", repr=False)
    twilio_from: str = ""
    twilio_allowed_to: tuple[str, ...] = ()
    public_base_url: str = ""
    # Secret the panel's dev-server proxy adds as x-voice-proxy-token; a tunnelled request reaches a non-public route only with it
    voice_proxy_token: str = field(default="", repr=False)


def proxy_token(raw: str) -> str:
    """The configured proxy secret, or "" when it is missing or too short to count (warned once, value never shown)."""
    if raw and len(raw) < PROXY_TOKEN_MIN_CHARS:
        logger.warning(f"VOICE_PROXY_TOKEN ignored: shorter than {PROXY_TOKEN_MIN_CHARS} characters, so the tunnel guard admits nothing")
        return ""
    return raw


def load_settings(env_file: Path | None = None) -> Settings:
    os.environ.pop("ANTHROPIC_API_KEY", None)
    file_values = dotenv_values(env_file) if env_file else {}

    def get(key: str, default: str) -> str:
        return os.environ.get(key) or file_values.get(key) or default

    keys = {"groq": get("GROQ_API_KEY", ""), "gemini": get("GEMINI_API_KEY", ""), "mistral": get("MISTRAL_API_KEY", ""),
            "ollama": "local"}  # a local Ollama needs no key; the link fails over fast if it is not running
    spec = get("VOICE_LLM_CHAIN", default_chain_spec(get("GEMINI_MODEL", ""), get("MISTRAL_MODEL", "")))
    api_raw = get("RENEWALS_API_BASE", Settings.api_base).rstrip("/")
    api_base = api_raw if (api_raw.endswith("/api/v1") or api_raw.endswith("/v1")) else f"{api_raw}/api/v1"
    sim_raw = get("SIMULATOR_BASE", Settings.simulator_base).rstrip("/")
    sim_base = sim_raw if sim_raw.endswith("/v1") else f"{sim_raw}/v1"

    return Settings(
        groq_api_key=keys["groq"],
        stt_model=get("VOICE_STT_MODEL", Settings.stt_model),
        llm_chain=parse_chain(spec, keys),
        intent_model=get("VOICE_INTENT_MODEL", Settings.intent_model),
        translate_model=get("VOICE_TRANSLATE_MODEL", Settings.translate_model),
        api_base=api_base,
        api_user=get("RENEWALS_API_USER", Settings.api_user),
        api_password=get("RENEWALS_API_PASSWORD", Settings.api_password),
        simulator_base=sim_base,
        human_agent_number=get("HUMAN_AGENT_NUMBER", "").replace(" ", ""),
        helpline_number=get("HELPLINE_NUMBER", Settings.helpline_number),
        tts_voice=get("VOICE_TTS_VOICE", Settings.tts_voice),
        voice_languages=parse_languages(get("VOICE_LANGUAGES", SpeechLanguage.ENGLISH)),
        twilio_account_sid=get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=get("TWILIO_AUTH_TOKEN", ""),
        twilio_from=get("TWILIO_FROM", "").replace(" ", ""),
        twilio_allowed_to=tuple(n.replace(" ", "") for n in get("TWILIO_ALLOWED_TO", "").split(",") if n.strip()),
        public_base_url=get("PUBLIC_BASE_URL", "").rstrip("/"),
        voice_proxy_token=proxy_token(get("VOICE_PROXY_TOKEN", "").strip()),
    )
