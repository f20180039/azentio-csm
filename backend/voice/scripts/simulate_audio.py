"""Play recorded customer turns through the agent, exactly as a live call would hear them, and write a readable report.

    python scripts/simulate_audio.py turn1.wav turn2.wav ...        # one conversation, files in order
    python scripts/simulate_audio.py path/to/folder                  # one conversation per sub-folder (or the folder itself)
    python scripts/simulate_audio.py folder --out report.md --base http://localhost:7861
"""
import argparse
import json
import sys
from pathlib import Path

import httpx

AUDIO = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}


def conversations(paths: list[Path]) -> list[tuple[str, list[Path]]]:
    if all(p.is_file() for p in paths):
        return [("conversation", paths)]
    out = []
    for p in paths:
        subdirs = sorted(d for d in p.iterdir() if d.is_dir())
        for d in subdirs or [p]:
            files = sorted(f for f in d.iterdir() if f.suffix.lower() in AUDIO)
            if files:
                out.append((d.name, files))
    return out


def run(base: str, name: str, files: list[Path]) -> dict:
    multipart = [("files", (f.name, f.read_bytes())) for f in files]
    resp = httpx.post(f"{base}/sim/audio", files=multipart, data={"speak": "false"}, timeout=180)
    resp.raise_for_status()
    return {"name": name, **resp.json()}


def report(results: list[dict]) -> str:
    lines = ["# Audio simulation report", ""]
    for r in results:
        lines += [f"## {r['name']}", f"Call `{r['call_id']}` · outcome **{r.get('outcome') or 'open'}**", "",
                  "| File | Heard | Intents | Verified | Tools | Agent said | ms |", "|---|---|---|---|---|---|---|"]
        for t in r["turns"]:
            heard = "*(no speech)*" if t["no_speech"] else t["transcript"]
            tools = ", ".join(x["name"] for x in t.get("tool_trace", []))
            said = (t.get("reply_text") or "").replace("|", "/")
            lines.append(f"| {t['file']} | {heard} | {', '.join(t.get('intents') or [])} | {'yes' if t['verified'] else 'no'} | {tools} | {said} | {t['latency_ms']} |")
        refs = sorted({ref for t in r["turns"] for ref in t.get("refs") or []})
        lines += ["", f"References raised: {', '.join(refs) or 'none'}", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--base", default="http://localhost:7861")
    ap.add_argument("--out", type=Path, default=Path("simulation-report.md"))
    args = ap.parse_args()
    results = [run(args.base, name, files) for name, files in conversations(args.paths)]
    args.out.write_text(report(results))
    args.out.with_suffix(".json").write_text(json.dumps(results, indent=2))
    print(f"{len(results)} conversation(s) → {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
