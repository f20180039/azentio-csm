"""Deterministic café ambience and SNR-controlled WAV mixing (standard library only)."""
from __future__ import annotations

import math
import random
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path


def read_mono(path: str | Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as src:
        if src.getnchannels() != 1 or src.getsampwidth() != 2:
            raise ValueError("expected 16-bit mono PCM WAV")
        rate = src.getframerate()
        raw = src.readframes(src.getnframes())
    return rate, [v / 32768.0 for (v,) in struct.iter_unpack("<h", raw)]


def write_mono(path: str | Path, rate: int, samples: list[float]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pcm = b"".join(struct.pack("<h", max(-32768, min(32767, round(x * 32767)))) for x in samples)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)


def rms(samples: list[float]) -> float:
    return math.sqrt(sum(x * x for x in samples) / max(1, len(samples)))


def mix_at_snr(speech: list[float], noise: list[float], snr_db: float = 5.0) -> list[float]:
    """Scale noise to the requested RMS SNR, looping or truncating it to speech length."""
    if not speech:
        return []
    if not noise or rms(noise) == 0:
        raise ValueError("noise must contain non-silent samples")
    aligned = [noise[i % len(noise)] for i in range(len(speech))]
    target_noise_rms = rms(speech) / (10 ** (snr_db / 20))
    gain = target_noise_rms / rms(aligned)
    return [max(-0.999, min(0.999, s + n * gain)) for s, n in zip(speech, aligned)]


def pink_noise(count: int, seed: int = 0) -> list[float]:
    """Generate reproducible low-pass (pink-ish) noise using a one-pole filter."""
    rng = random.Random(seed)
    out: list[float] = []
    state = 0.0
    for _ in range(count):
        state = 0.985 * state + 0.1726 * rng.uniform(-1.0, 1.0)
        out.append(state)
    level = rms(out) or 1.0
    return [x / level for x in out]


def render_noisy(speech_path: str | Path, output_path: str | Path,
                 cafe_voices: list[list[float]] | None = None, seed: int = 0,
                 snr_db: float = 5.0, pad_seconds: float = 0.7) -> None:
    """Mix three unrelated background speech clips and pink noise, then add room-tone pads."""
    rate, speech = read_mono(speech_path)
    if not speech:
        raise ValueError("speech WAV is empty")
    rng = random.Random(seed)
    background = [0.0] * len(speech)
    for clip in (cafe_voices or [])[:3]:
        if clip:
            offset = rng.randrange(max(1, len(speech)))
            for i, sample in enumerate(clip):
                background[(offset + i) % len(background)] += sample / 3
    pink = None
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        with tempfile.TemporaryDirectory() as td:
            noise_path = Path(td) / "pink.wav"
            subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i",
                            f"anoisesrc=color=pink:amplitude=0.3:seed={seed}:duration={len(speech) / rate}:sample_rate={rate}",
                            "-ac", "1", "-ar", str(rate), str(noise_path)], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _, pink = read_mono(noise_path)
    if not pink:
        pink = pink_noise(len(speech), seed)
    pink = [pink[i % len(pink)] for i in range(len(speech))]
    background = [b + p * 0.3 for b, p in zip(background, pink)]
    mixed = mix_at_snr(speech, background, snr_db)
    pad_noise = pink_noise(round(rate * pad_seconds), seed + 1)
    pad = [x * 0.025 for x in pad_noise]
    write_mono(output_path, rate, pad + mixed + pad)

