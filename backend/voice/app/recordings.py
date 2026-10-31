"""What the caller said, kept per customer turn so staff can play it back next to the transcript. Stored on the voice
service's disk under VOICE_RECORDINGS_DIR (all callers here are synthetic; real callers would need a retention policy)."""
import io
import os
import wave
from pathlib import Path
from uuid import UUID

RECORDINGS_DIR = Path(os.environ.get("VOICE_RECORDINGS_DIR", Path(__file__).resolve().parents[1] / "data" / "recordings"))
SUFFIXES = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm")
MEDIA_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".flac": "audio/flac", ".webm": "audio/webm"}


def join_wavs(parts: list[bytes]) -> bytes | None:
    """One WAV from the segments of a caller turn (same format, as the live speech-to-text produces them)."""
    frames, params = [], None
    for part in parts:
        try:
            with wave.open(io.BytesIO(part)) as w:
                params = params or w.getparams()
                frames.append(w.readframes(w.getnframes()))
        except (wave.Error, EOFError):
            continue
    if not frames or params is None:
        return None
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(b"".join(frames))
    return out.getvalue()


def _dir(call_id: str) -> Path:
    return RECORDINGS_DIR / str(UUID(str(call_id)))  # a UUID can't climb out of the folder


def save(call_id: str, seq: int, audio: bytes, suffix: str = ".wav") -> Path:
    suffix = suffix.lower() if suffix.lower() in SUFFIXES else ".wav"
    folder = _dir(call_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{int(seq)}{suffix}"
    path.write_bytes(audio)
    return path


def find(call_id: str, seq: int) -> Path | None:
    try:
        folder = _dir(call_id)
    except ValueError:
        return None
    return next((folder / f"{int(seq)}{s}" for s in SUFFIXES if (folder / f"{int(seq)}{s}").is_file()), None)
