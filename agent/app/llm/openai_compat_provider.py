import httpx

from ..config import Settings
from .gateway import LlmRequest, LlmResponse, ProviderError

# Gemini, Groq and Mistral all expose the OpenAI chat-completions shape.
ENDPOINTS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
}


class OpenAICompatProvider:
    def __init__(self, name: str, settings: Settings, client: httpx.Client | None = None):
        cfg = settings.compat[name]
        self.name = name
        self._url = ENDPOINTS[name]
        self._key = cfg.api_key
        self._models = {"extract": cfg.model, "explain": cfg.reasoning_model}
        self._client = client or httpx.Client(timeout=settings.llm_timeout_s)

    def complete(self, req: LlmRequest) -> LlmResponse:
        if not self._key:
            raise ProviderError(f"{self.name}: no API key")
        model = self._models.get(req.purpose, self._models["extract"])
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": min(req.max_tokens, 8192),
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
        }
        try:
            resp = self._client.post(self._url, json=payload, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: connection error: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
            text = body["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError) as exc:
            raise ProviderError(f"{self.name}: unexpected response shape") from exc
        if not text.strip():
            raise ProviderError(f"{self.name}: empty response")
        usage = body.get("usage") or {}
        return LlmResponse(
            text=text,
            provider=self.name,
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
