import anthropic

from ..config import Settings
from .gateway import LlmRequest, LlmResponse, ProviderError

# Extraction is high-volume and shallow; explanations need more judgement.
_EFFORT = {"extract": "low", "explain": "medium"}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: anthropic.Anthropic | None = None

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(timeout=self._settings.llm_timeout_s, max_retries=1)
        return self._client

    def complete(self, req: LlmRequest) -> LlmResponse:
        model = (
            self._settings.anthropic_reasoning_model
            if req.purpose == "explain"
            else self._settings.anthropic_model
        )
        try:
            message = self._get_client().messages.create(
                model=model,
                max_tokens=req.max_tokens,
                # The system prompt is stable per schema, so it is the cache prefix.
                system=[{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
                output_config={"effort": _EFFORT.get(req.purpose, "medium")},
                messages=[{"role": "user", "content": req.user}],
            )
        except anthropic.RateLimitError as exc:
            raise ProviderError(f"rate limited: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"connection error: {exc}") from exc
        except anthropic.AnthropicError as exc:
            raise ProviderError(str(exc)) from exc
        except TypeError as exc:  # the SDK raises TypeError when no credentials resolve
            raise ProviderError(f"no Anthropic credentials: {exc}") from exc

        if message.stop_reason == "refusal":
            raise ProviderError("model refused the request")
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text.strip():
            raise ProviderError(f"empty response (stop_reason={message.stop_reason})")
        return LlmResponse(
            text=text,
            provider=self.name,
            model=model,
            input_tokens=message.usage.input_tokens + (message.usage.cache_read_input_tokens or 0),
            output_tokens=message.usage.output_tokens,
        )
