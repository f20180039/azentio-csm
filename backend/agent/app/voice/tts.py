"""
Text to speech. Reused from the solarfile-reels narration pipeline
(backend/app/pipeline/tts.py, commit f089eaa); declared in the README.

Providers, chosen with TTS_PROVIDER:
  - edge_tts:   Microsoft neural voices via edge-tts (free, no GPU, needs internet)
  - elevenlabs: ElevenLabs API, best quality but billed per character
"""

import logging
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"


async def _generate_edge_tts(text: str, voice: str, output_path: Path) -> None:
    try:
        import edge_tts
    except ImportError:
        raise RuntimeError("edge-tts is not installed. Run: pip install edge-tts")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    await edge_tts.Communicate(text, voice).save(str(output_path))
    logger.info("edge-tts wrote %d bytes to %s", output_path.stat().st_size, output_path)


async def _generate_elevenlabs_tts(
    text: str,
    voice_id: str,
    api_key: str,
    output_path: Path,
    model: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    if not api_key:
        raise RuntimeError("TTS_PROVIDER=elevenlabs but ELEVENLABS_API_KEY is not set in .env")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "text": text,
        "model_id": model,
        "voice_settings": {
            # Slightly higher stability than default so the tone does not wander mid-sentence.
            "stability": 0.45,
            "similarity_boost": 0.8,
            "style": 0.15,
            "use_speaker_boost": True,
        },
    }
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    logger.info("ElevenLabs request: %d chars, voice=%s", len(text), voice_id)

    async with httpx.AsyncClient(timeout=180, transport=transport) as client:
        resp = await client.post(f"{ELEVENLABS_TTS_URL}/{voice_id}", json=payload, headers=headers)

    if resp.status_code >= 400:
        body = resp.text[:600]
        # ElevenLabs returns 401 (not 429) when a key is out of credits, so branch on the body.
        if "quota_exceeded" in body:
            raise RuntimeError(
                "ElevenLabs key has no credits remaining. Raise the key's credit limit or "
                f"set TTS_PROVIDER=edge_tts to keep working for free.\nAPI said: {body}"
            )
        if "missing_permissions" in body:
            raise RuntimeError(
                f"ElevenLabs key is missing the text_to_speech scope.\nAPI said: {body}"
            )
        if resp.status_code == 401:
            raise RuntimeError(f"ElevenLabs rejected the API key (401): {body}")
        raise RuntimeError(f"ElevenLabs error {resp.status_code}: {body}")

    output_path.write_bytes(resp.content)
    logger.info("ElevenLabs wrote %d bytes to %s", output_path.stat().st_size, output_path)


async def synthesize(text: str, output_path: Path, voice: str | None = None) -> Path:
    """Speak `text` into an MP3 at `output_path` and return the path."""
    provider = settings.tts_provider
    if provider == "edge_tts":
        await _generate_edge_tts(text, voice or settings.edge_tts_voice, output_path)
    elif provider == "elevenlabs":
        await _generate_elevenlabs_tts(
            text,
            voice or settings.elevenlabs_voice_id,
            settings.elevenlabs_api_key,
            output_path,
            settings.elevenlabs_model,
        )
    else:
        raise ValueError(f"Unknown TTS provider '{provider}'. Set TTS_PROVIDER to 'edge_tts' or 'elevenlabs'.")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"TTS produced no output at {output_path}")
    return output_path
