"""Render eval utterances or scenario turns to cached, 16 kHz mono WAV files."""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts

if __package__:
    from .noise import read_mono, render_noisy
else:  # Support direct execution as documented in the Pavan task.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from eval.audio.noise import read_mono, render_noisy

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "out"
VOICES = {"in": "en-IN-NeerjaNeural", "gb": "en-GB-RyanNeural", "ng": "en-NG-EzinneNeural", "us": "en-US-GuyNeural"}
CAFE_LINES = ["The train leaves from platform six this afternoon.", "Please leave the package beside the front desk.", "The weekend market opens at nine in the morning."]


def load_inputs(source: str) -> list[dict]:
    if source == "utterances":
        with (ROOT / "utterances.csv").open(encoding="utf-8", newline="") as f:
            return [{"id": row["id"], "text": row["text"], "intents": row["intents"].split("|")} for row in csv.DictReader(f)]
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("scenario rendering requires PyYAML; install it with pip install pyyaml") from exc
    rows = []
    for path in sorted((ROOT / "scenarios").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for n, turn in enumerate(data["turns"], 1):
            rows.append({"id": data["id"], "turn": n, "text": turn["say"],
                         "intents": turn.get("expect", {}).get("intents", [])})
    return rows


def manifest_rows(rows: list[dict], source: str, accents: list[str], conditions: list[str], out: Path) -> list[dict]:
    manifest = []
    for row in rows:
        suffix = f"_t{row['turn']:02d}" if "turn" in row else ""
        for accent in accents:
            for condition in conditions:
                dest = out / source / accent / condition / f"{row['id']}{suffix}.wav"
                manifest.append({"file": dest.relative_to(out).as_posix(), "text": row["text"],
                                 "intents": row["intents"], "accent": accent, "condition": condition})
    return manifest


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is required to convert edge-tts audio to WAV")
    return exe


async def _synthesize(text: str, voice: str, wav_path: Path) -> None:
    key = hashlib.sha256(f"{voice}\0{text}".encode()).hexdigest()
    cache = Path(tempfile.gettempdir()) / "azentio-voice-tts-cache" / f"{key}.wav"
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        mp3 = cache.with_suffix(".mp3")
        await edge_tts.Communicate(text, voice).save(str(mp3))
        subprocess.run([_ffmpeg(), "-y", "-i", str(mp3), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(cache)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        mp3.unlink(missing_ok=True)
    shutil.copyfile(cache, wav_path)


async def _background(voice: str, target: Path, line: str) -> list[float]:
    await _synthesize(line, voice, target)
    _, samples = read_mono(target)
    target.unlink(missing_ok=True)
    return samples


async def render(source: str, accents: list[str], conditions: list[str], limit: int | None = None, out: Path = OUT) -> list[dict]:
    rows = load_inputs(source)
    if limit is not None:
        rows = rows[:limit]
    manifest: list[dict] = []
    for row in rows:
        suffix = f"_t{row['turn']:02d}" if "turn" in row else ""
        for accent in accents:
            voice = VOICES[accent]
            for condition in conditions:
                dest = out / source / accent / condition / f"{row['id']}{suffix}.wav"
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory() as td:
                        clean = Path(td) / "clean.wav"
                        await _synthesize(row["text"], voice, clean)
                        if condition == "clean":
                            shutil.copyfile(clean, dest)
                        else:
                            clips = []
                            other_voices = [v for key, v in VOICES.items() if key != accent][:3]
                            for i, (line, bg_voice) in enumerate(zip(CAFE_LINES, other_voices)):
                                clips.append(await _background(bg_voice, Path(td) / f"bg{i}.wav", line))
                            render_noisy(clean, dest, clips, seed=int(hashlib.sha256(row["id"].encode()).hexdigest()[:8], 16))
    manifest = manifest_rows(rows, source, accents, conditions, out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["utterances", "scenarios"], required=True)
    parser.add_argument("--accents", default="in,gb,ng,us")
    parser.add_argument("--conditions", default="clean,noisy")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    accents, conditions = args.accents.split(","), args.conditions.split(",")
    if set(accents) - VOICES.keys() or set(conditions) - {"clean", "noisy"}:
        parser.error("unknown accent or condition")
    manifest = asyncio.run(render(args.source, accents, conditions, args.limit, args.out))
    print(f"Rendered {len(manifest)} WAV files; manifest: {args.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
