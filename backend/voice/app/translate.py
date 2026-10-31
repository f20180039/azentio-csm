"""English for a Kannada or Hindi turn, written to the turn's meta for the operator panel. The original stays the record.
One Groq chat completion at temperature 0; None on any failure, so a translation can never cost a reply or a call."""

import asyncio

import httpx
from loguru import logger

from .llm_chain import PROVIDERS

SYSTEM_PROMPT = ("Translate this utterance from a bank customer-service call into English. Keep every number, amount, date and "
                 "reference (for example SR-40102, ₹12,450) exactly as written. Output only the translation.")
TRANSLATE_TIMEOUT_SECS = 8.0
MAX_TOKENS = 400


async def to_english(text: str, *, api_key: str, model: str, transport: httpx.AsyncBaseTransport | None = None,
                     timeout: float = TRANSLATE_TIMEOUT_SECS) -> str | None:
    """The English translation of `text`, or None: no key, blank input, HTTP error, timeout, empty or unreadable output."""
    if not api_key or not (text or "").strip():
        return None
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
        "temperature": 0,
        "max_completion_tokens": MAX_TOKENS,
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            resp = await asyncio.wait_for(
                client.post(f"{PROVIDERS['groq']}/chat/completions", json=body, headers={"Authorization": f"Bearer {api_key}"}),
                timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        english = (content or "").strip() if isinstance(content, str) else ""
        if english:
            return english
        logger.info("translation: empty output")
    except httpx.HTTPStatusError as e:
        logger.warning(f"translation: HTTP {e.response.status_code}")
    except Exception as e:
        logger.warning(f"translation: {type(e).__name__}")
    return None
