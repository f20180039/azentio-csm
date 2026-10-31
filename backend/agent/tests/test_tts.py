import asyncio

import httpx
import pytest

from app.voice.tts import _generate_elevenlabs_tts


def _run(status: int, body: bytes, tmp_path):
    transport = httpx.MockTransport(lambda req: httpx.Response(status, content=body))
    out = tmp_path / "reply.mp3"
    asyncio.run(_generate_elevenlabs_tts("hello", "voice", "key", out, "model", transport))
    return out


def test_elevenlabs_writes_audio(tmp_path):
    assert _run(200, b"ID3audio", tmp_path).read_bytes() == b"ID3audio"


def test_elevenlabs_out_of_credits_is_not_reported_as_bad_key(tmp_path):
    with pytest.raises(RuntimeError, match="no credits"):
        _run(401, b'{"detail":{"status":"quota_exceeded"}}', tmp_path)


def test_elevenlabs_needs_a_key(tmp_path):
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        asyncio.run(_generate_elevenlabs_tts("hi", "v", "", tmp_path / "x.mp3", "m"))
