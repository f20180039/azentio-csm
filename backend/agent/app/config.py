import os
from dataclasses import dataclass, field


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class CompatProvider:
    api_key: str
    model: str
    reasoning_model: str


def _compat(prefix: str, model: str, reasoning_model: str) -> CompatProvider:
    return CompatProvider(
        api_key=os.getenv(f"{prefix}_API_KEY", ""),
        model=os.getenv(f"{prefix}_MODEL", model),
        reasoning_model=os.getenv(f"{prefix}_REASONING_MODEL", reasoning_model),
    )


@dataclass(frozen=True)
class Settings:
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock"))
    llm_fallback: list[str] = field(default_factory=lambda: _list(os.getenv("LLM_FALLBACK", "ollama,mock")))
    llm_cooldown_s: float = field(default_factory=lambda: float(os.getenv("LLM_COOLDOWN_S", "30")))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5"))
    anthropic_reasoning_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_REASONING_MODEL", "claude-sonnet-5-5")
    )
    compat: dict[str, CompatProvider] = field(
        default_factory=lambda: {
            "gemini": _compat("GEMINI", "gemini-2.5-flash", "gemini-2.5-flash"),
            "groq": _compat("GROQ", "openai/gpt-oss-120b", "openai/gpt-oss-120b"),
            "mistral": _compat("MISTRAL", "mistral-small-latest", "mistral-large-latest"),
        }
    )
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2"))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "60")))
    tts_provider: str = field(default_factory=lambda: os.getenv("TTS_PROVIDER", "edge_tts"))
    edge_tts_voice: str = field(default_factory=lambda: os.getenv("EDGE_TTS_VOICE", "en-IN-NeerjaNeural"))
    elevenlabs_api_key: str = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", ""))
    elevenlabs_voice_id: str = field(default_factory=lambda: os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"))
    elevenlabs_model: str = field(default_factory=lambda: os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2"))
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pages: int = 50


settings = Settings()
