"""Provider-neutral LLM gateway with an ordered fallback chain.

Providers return plain text; callers own parsing and validation so every
provider is held to the same schema checks."""
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from ..config import Settings
from ..logs import log

logger = logging.getLogger("agent.llm")


@dataclass
class LlmRequest:
    purpose: str  # "extract" | "explain"; picks the model tier
    system: str
    user: str
    mock_response: Callable[[], str]  # deterministic answer used by the mock provider
    max_tokens: int = 16000


@dataclass
class LlmResponse:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    attempts: list[str] = field(default_factory=list)  # "provider:error" for each failed provider


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def complete(self, req: LlmRequest) -> LlmResponse: ...


class MockProvider:
    name = "mock"

    def complete(self, req: LlmRequest) -> LlmResponse:
        return LlmResponse(text=req.mock_response(), provider="mock", model="mock")


class Gateway:
    def __init__(self, providers: list[Provider], cooldown_s: float = 0.0, clock: Callable[[], float] = time.monotonic):
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = providers
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._cooling_until: dict[str, float] = {}

    @property
    def chain(self) -> list[str]:
        return [p.name for p in self.providers]

    def _ordered(self) -> list[Provider]:
        # A provider that failed recently goes to the back instead of costing every request a timeout.
        now = self._clock()
        ready = [p for p in self.providers if self._cooling_until.get(p.name, 0) <= now]
        cooling = [p for p in self.providers if p not in ready]
        return ready + cooling

    def complete(self, req: LlmRequest) -> LlmResponse:
        failures: list[str] = []
        for provider in self._ordered():
            started = time.perf_counter()
            try:
                resp = provider.complete(req)
            except ProviderError as exc:
                failures.append(f"{provider.name}:{exc}")
                self._cooling_until[provider.name] = self._clock() + self._cooldown_s
                log(logger, "llm_provider_failed", provider=provider.name, purpose=req.purpose, error=str(exc)[:200])
                continue
            self._cooling_until.pop(provider.name, None)
            resp.latency_ms = int((time.perf_counter() - started) * 1000)
            resp.attempts = failures
            log(
                logger,
                "llm_call",
                provider=resp.provider,
                model=resp.model,
                purpose=req.purpose,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
                latency_ms=resp.latency_ms,
                fallbacks=len(failures),
            )
            return resp
        raise ProviderError("all providers failed: " + "; ".join(failures))


def build_gateway(settings: Settings) -> Gateway:
    from .anthropic_provider import AnthropicProvider
    from .ollama_provider import OllamaProvider
    from .openai_compat_provider import ENDPOINTS, OpenAICompatProvider

    factories: dict[str, Callable[[], Provider]] = {
        "anthropic": lambda: AnthropicProvider(settings),
        "ollama": lambda: OllamaProvider(settings),
        "mock": MockProvider,
    }
    for compat_name in ENDPOINTS:
        factories[compat_name] = lambda n=compat_name: OpenAICompatProvider(n, settings)
    names: list[str] = []
    for name in [settings.llm_provider, *settings.llm_fallback]:
        if name not in factories:
            raise ValueError(f"unknown LLM provider '{name}'")
        if name not in names:
            names.append(name)
    return Gateway([factories[n]() for n in names], cooldown_s=settings.llm_cooldown_s)
