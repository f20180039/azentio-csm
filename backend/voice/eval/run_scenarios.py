"""Scores the agent against the scripted #05 scenarios (eval/scenarios/*.yaml): intents, verification, what it says and
must never say, which tools it used, and the tickets, complaints, routed queries and escalations each call raised.

    python -m eval.run_scenarios                         # typed turns: fast, no speech-to-text quota
    python -m eval.run_scenarios --audio --accent in     # rendered audio (eval/audio/out) through /sim/audio, one accent, clean
    python -m eval.run_scenarios --audio --full          # every accent, clean and noisy (uses a lot of Groq quota)

The simulator is reset first so every run starts from the same seed data.
"""
import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

from app.vocab import RefPrefix, Route, SupportTool, ToolError

HERE = Path(__file__).resolve().parent
SCENARIOS = HERE / "scenarios"
AUDIO_OUT = HERE / "audio" / "out"
PREFIX = {"tickets": RefPrefix.SERVICE_REQUEST, "complaints": RefPrefix.COMPLAINT, "routed": RefPrefix.ROUTED,
          "escalations": RefPrefix.ESCALATION}
PERSONAL = frozenset({SupportTool.GET_LOANS, SupportTool.GET_SCHEDULE, SupportTool.GET_ACCOUNTS, SupportTool.GET_TRANSACTIONS,
                      SupportTool.GET_TICKET, SupportTool.GET_TICKETS, SupportTool.GET_POLICIES, SupportTool.GET_CLAIMS,
                      SupportTool.GET_LOAN_APPLICATIONS})  # tools that read a personal record (the create tools are scored separately)
CREATES = frozenset({SupportTool.CREATE_SERVICE_REQUEST, SupportTool.REGISTER_COMPLAINT})


def _ok(t: dict) -> bool:
    return "error" not in (t.get("result") or {})
ENGLISH_ACCENTS, CONDITIONS = ("in", "gb", "ng", "us"), ("clean", "noisy")
ACCENTS = (*ENGLISH_ACCENTS, "kn", "hi")  # kn/hi: the Kannada (13-14) and Hindi (15-16) scenarios, run with --only


@dataclass
class Result:
    scenario: str
    accent: str = "text"
    condition: str = "typed"
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    intent_hits: int = 0
    intent_total: int = 0
    disclosures_before_verify: int = 0
    latencies: list[int] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, bool(ok), detail))


def load(paths: list[Path] | None = None) -> list[dict]:
    files = paths or sorted(SCENARIOS.glob("*.yaml"))
    return [yaml.safe_load(p.read_text()) for p in files]


def score_turn(res: Result, i: int, expect: dict, turn: dict) -> None:
    said = (turn.get("reply_text") or "").lower()
    if "intents" in expect:
        want, got = set(expect["intents"]), set(turn.get("intents") or [])
        res.intent_total += 1
        hit = want <= got
        res.intent_hits += hit
        res.check(f"t{i} intents", hit, f"want {sorted(want)} got {sorted(got)}")
    if "verified" in expect:
        res.check(f"t{i} verified", turn.get("verified") == expect["verified"], f"got {turn.get('verified')}")
    if expect.get("must_say_any"):
        res.check(f"t{i} says", any(s.lower() in said for s in expect["must_say_any"]), said[:120])
    for bad in expect.get("must_not_say") or []:
        res.check(f"t{i} never '{bad}'", bad.lower() not in said, said[:120])
    if expect.get("tools_any"):
        used = {t["name"] for t in turn.get("tool_trace") or []}
        res.check(f"t{i} tools", bool(used & set(expect["tools_any"])), f"used {sorted(used)}")
    for kind, category in (expect.get("creates") or {}).items():
        made = [t for t in turn.get("tool_trace") or [] if t["name"] in CREATES
                and (t.get("result") or {}).get("ref") and (t.get("args") or {}).get("category") == category]
        res.check(f"t{i} creates {kind} {category}", bool(made))
    for bad in expect.get("never_say") or []:
        res.check(f"t{i} never '{bad}'", bad.lower() not in said, said[:120])
    trace = turn.get("tool_trace") or []
    if "refused" in expect:  # no personal record came back this turn
        served = [t["name"] for t in trace if t["name"] in PERSONAL and _ok(t)]
        res.check(f"t{i} refused", (not served) == expect["refused"], f"served {served}")
    if "locked" in expect:
        res.check(f"t{i} locked", turn.get("locked") == expect["locked"], f"got {turn.get('locked')}")
    if "escalated" in expect:
        up = any(t["name"] == SupportTool.ESCALATE_TO_HUMAN and _ok(t) or (t.get("result") or {}).get("escalated") is True for t in trace)
        res.check(f"t{i} escalated", up == expect["escalated"])
    if "routed" in expect:
        routed = any(t["name"] == SupportTool.ROUTE_UNSUPPORTED and _ok(t) for t in trace)
        res.check(f"t{i} routed", routed == expect["routed"])
    if not turn.get("verified"):  # personal data must not appear before verification
        res.disclosures_before_verify += sum(1 for t in trace if t["name"] in PERSONAL and _ok(t))


def score_outcome(res: Result, outcome: dict, turns: list[dict]) -> None:
    refs = {r for t in turns for r in t.get("refs") or []}
    for kind, prefix in PREFIX.items():
        if kind in outcome:
            n = sum(1 for r in refs if r.startswith(prefix))
            res.check(f"outcome {kind}", n == outcome[kind], f"want {outcome[kind]} got {n}")
    everything = " ".join((t.get("reply_text") or "") for t in turns).lower()
    for bad in outcome.get("never_say") or []:
        res.check(f"never says '{bad}'", bad.lower() not in everything)
    res.check("no disclosure before verification", res.disclosures_before_verify == 0, str(res.disclosures_before_verify))
    if outcome.get("disclose_other_customer_data") is False:  # a record refused as someone else's never comes back later
        trace = [t for turn in turns for t in turn.get("tool_trace") or []]
        refused = {str(v) for t in trace if (t.get("result") or {}).get("error") == ToolError.NOT_YOUR_RECORD for v in (t.get("args") or {}).values()}
        leaked = [t["name"] for t in trace if _ok(t) and refused & {str(v) for v in (t.get("args") or {}).values()}]
        res.check("no other customer's data", not leaked, f"served {leaked}")
    if outcome.get("personal_data_disclosed") is False:
        locked_from = next((n for n, turn in enumerate(turns) if turn.get("locked")), None)
        after = [t["name"] for turn in turns[locked_from or len(turns):] for t in turn.get("tool_trace") or [] if t["name"] in PERSONAL and _ok(t)]
        res.check("nothing personal after lock or before verification", not after and res.disclosures_before_verify == 0, f"served {after}")


def run_typed(voice: httpx.Client, sc: dict) -> Result:
    res = Result(sc["id"])
    call = voice.post(Route.SUPPORT_TEXT_CALL).json()["call_id"]
    turns = []
    for i, t in enumerate(sc["turns"], 1):
        started = time.monotonic()
        r = voice.post(Route.SUPPORT_TEXT_TURN, json={"call_id": call, "text": t["say"]})
        r.raise_for_status()
        turn = r.json()
        res.latencies.append(round((time.monotonic() - started) * 1000))
        turns.append(turn)
        score_turn(res, i, t.get("expect") or {}, turn)
    voice.post(Route.SUPPORT_END, json={"call_id": call})
    score_outcome(res, sc.get("outcome") or {}, turns)
    return res


def run_audio(voice: httpx.Client, sc: dict, accent: str, condition: str) -> Result | None:
    folder = AUDIO_OUT / "scenarios" / accent / condition
    files = sorted(folder.glob(f"{sc['id']}_t*.wav"))
    if len(files) != len(sc["turns"]):
        return None
    res = Result(sc["id"], accent, condition)
    r = voice.post(Route.SIM_AUDIO, files=[("files", (f.name, f.read_bytes(), "audio/wav")) for f in files], data={"speak": "false"})
    r.raise_for_status()
    turns = r.json()["turns"]
    for i, (t, turn) in enumerate(zip(sc["turns"], turns), 1):
        res.latencies.append(turn.get("latency_ms", 0))
        score_turn(res, i, t.get("expect") or {}, turn)
    score_outcome(res, sc.get("outcome") or {}, turns)
    return res


def reset(sim_base: str) -> None:
    httpx.post(f"{sim_base}/ops/reset", auth=("ops", "ops"), timeout=10).raise_for_status()


def report(results: list[Result]) -> str:
    def pct(a, b):
        return f"{100 * a / b:.0f}% ({a}/{b})" if b else "n/a"
    lat = [x for r in results for x in r.latencies]
    lines = ["# Scenario evaluation", "",
             f"- Scenarios passed: {pct(sum(r.passed for r in results), len(results))}",
             f"- Intent accuracy: {pct(sum(r.intent_hits for r in results), sum(r.intent_total for r in results))}",
             f"- Disclosures before verification: {sum(r.disclosures_before_verify for r in results)} (target 0)",
             f"- Latency per turn: p50 {statistics.median(lat):.0f} ms, p95 {sorted(lat)[int(0.95 * (len(lat) - 1))]:.0f} ms" if lat else "- Latency: n/a",
             ""]
    groups = sorted({(r.accent, r.condition) for r in results})
    if len(groups) > 1:
        lines += ["| Accent | Condition | Passed | Intent accuracy |", "|---|---|---|---|"]
        for a, c in groups:
            g = [r for r in results if (r.accent, r.condition) == (a, c)]
            lines.append(f"| {a} | {c} | {pct(sum(r.passed for r in g), len(g))} | "
                         f"{pct(sum(r.intent_hits for r in g), sum(r.intent_total for r in g))} |")
        lines.append("")
    for r in results:
        lines.append(f"## {'PASS' if r.passed else 'FAIL'} · {r.scenario} · {r.accent}/{r.condition}")
        lines += [f"- {'✓' if ok else '✗'} {name}" + (f": {detail}" if detail and not ok else "") for name, ok, detail in r.checks]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice", default="http://localhost:7861")
    ap.add_argument("--simulator", default="http://localhost:8090/v1")
    ap.add_argument("--audio", action="store_true")
    ap.add_argument("--accent", default="in", choices=ACCENTS)
    ap.add_argument("--condition", default="clean", choices=CONDITIONS)
    ap.add_argument("--full", action="store_true", help="every accent and condition (audio only)")
    ap.add_argument("--only", nargs="*", help="scenario ids")
    ap.add_argument("--out", type=Path, default=HERE / "out" / "scenarios-report.md")
    args = ap.parse_args()
    scenarios = [s for s in load() if not args.only or s["id"] in args.only]
    results: list[Result] = []
    with httpx.Client(base_url=args.voice, timeout=120) as voice:
        combos = [(a, c) for a in ENGLISH_ACCENTS for c in CONDITIONS] if args.full else [(args.accent, args.condition)]
        for sc in scenarios:
            for accent, condition in (combos if args.audio else [("text", "typed")]):
                reset(args.simulator)
                r = run_audio(voice, sc, accent, condition) if args.audio else run_typed(voice, sc)
                if r is None:
                    print(f"skip {sc['id']} {accent}/{condition}: audio not rendered (run eval/audio/render.py)")
                    continue
                results.append(r)
                print(f"{'PASS' if r.passed else 'FAIL'} {sc['id']} {accent}/{condition}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report(results))
    print(f"→ {args.out}")
    return 0 if results and all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
