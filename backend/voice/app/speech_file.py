"""Recorded-audio path of the speech front end: decode any audio file to 16 kHz mono, keep only the speech the same Silero
model finds in live calls, compress it losslessly and transcribe it, dropping transcripts the model invents from noise."""
import asyncio
import io
from dataclasses import dataclass

import av
import httpx
import numpy as np
from pipecat.audio.vad.silero import SileroVADAnalyzer

from . import speech

RATE = 16000
FRAME = 512  # Silero's window at 16 kHz (32 ms)
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


@dataclass
class Transcript:
    text: str | None  # None: no speech, or only noise the model turned into words
    speech_secs: float
    upload_bytes: int
    reason: str = ""


def decode_pcm16(data: bytes) -> np.ndarray:
    """Any container/codec PyAV reads → int16 mono samples at 16 kHz."""
    out = []
    with av.open(io.BytesIO(data)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        for frame in container.decode(audio=0):
            for r in resampler.resample(frame):
                out.append(np.frombuffer(bytes(r.planes[0])[: r.samples * 2], np.int16))
        for r in resampler.resample(None):
            out.append(np.frombuffer(bytes(r.planes[0])[: r.samples * 2], np.int16))
    return np.concatenate(out) if out else np.zeros(0, np.int16)


def speech_regions(pcm: np.ndarray, vad: SileroVADAnalyzer | None = None) -> list[tuple[int, int]]:
    """Sample ranges Silero marks as speech, padded with pre/post roll and merged across short gaps."""
    vad = vad or SileroVADAnalyzer(sample_rate=RATE)
    vad.set_sample_rate(RATE)
    flags = [vad.voice_confidence(pcm[i:i + FRAME].tobytes()) >= speech.VAD_CONFIDENCE
             for i in range(0, len(pcm) - FRAME + 1, FRAME)]
    regions, start = [], None
    for i, on in enumerate(flags + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if (i - start) * FRAME / RATE >= speech.MIN_SPEECH_SECS:
                regions.append((start * FRAME, i * FRAME))
            start = None
    pre, post, gap = (int(s * RATE) for s in (speech.PRE_ROLL_SECS, speech.POST_ROLL_SECS, speech.MERGE_GAP_SECS))
    merged: list[tuple[int, int]] = []
    for a, b in regions:
        a, b = max(0, a - pre), min(len(pcm), b + post)
        if merged and a - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


def encode_flac(pcm: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with av.open(buf, "w", format="flac") as out:
        stream = out.add_stream("flac", rate=RATE, layout="mono")
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = RATE
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


def trimmed_speech(data: bytes) -> tuple[np.ndarray, float]:
    pcm = decode_pcm16(data)
    regions = speech_regions(pcm)
    if not regions:
        return np.zeros(0, np.int16), 0.0
    kept = np.concatenate([pcm[a:b] for a, b in regions])
    return kept, len(kept) / RATE


async def transcribe_file(data: bytes, *, api_key: str, model: str, transport: httpx.AsyncBaseTransport | None = None) -> Transcript:
    pcm, secs = await asyncio.to_thread(trimmed_speech, data)
    if secs == 0:
        return Transcript(None, 0.0, 0, "no speech detected")
    flac = await asyncio.to_thread(encode_flac, pcm)
    form = {"model": model, "language": speech.LANGUAGE, "prompt": speech.DOMAIN_PROMPT, "response_format": "verbose_json", "temperature": "0"}
    async with httpx.AsyncClient(timeout=30.0, transport=transport) as client:
        resp = await client.post(GROQ_STT_URL, headers={"Authorization": f"Bearer {api_key}"}, data=form,
                                 files={"file": ("speech.flac", flac, "audio/flac")})
        resp.raise_for_status()
        body = resp.json()
    kept = [s for s in body.get("segments") or [] if not speech.is_invented_segment(s)]
    text = " ".join(s.get("text", "").strip() for s in kept).strip() if body.get("segments") else (body.get("text") or "").strip()
    if not text or speech.is_phantom(text):
        return Transcript(None, secs, len(flac), "only noise or a phantom phrase")
    return Transcript(text, secs, len(flac))
