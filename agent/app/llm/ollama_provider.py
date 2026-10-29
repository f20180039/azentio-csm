import httpx

from ..config import Settings
from .gateway import LlmRequest, LlmResponse, ProviderError


class OllamaProvider:
    """Local open-weight model, for offline demos and on-prem deployments."""

    name = "ollama"

    def __init__(self, settings: Settings):
        self._url = settings.ollama_url.rstrip("/") + "/api/chat"
        self._model = settings.ollama_model
        self._timeout = settings.llm_timeout_s

    def complete(self, req: LlmRequest) -> LlmResponse:
        payload = {
            "model": self._model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
        }
        try:
            resp = httpx.post(self._url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama request failed: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("ollama returned non-JSON") from exc

        text = body.get("message", {}).get("content", "")
        if not text.strip():
            raise ProviderError("ollama returned an empty message")
        return LlmResponse(
            text=text,
            provider=self.name,
            model=self._model,
            input_tokens=body.get("prompt_eval_count", 0),
            output_tokens=body.get("eval_count", 0),
        )
