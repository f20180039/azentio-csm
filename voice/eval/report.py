"""Report for a simulated-customer run. Re-render a saved run: python -m eval.report eval/out/latest.json"""
import json
import statistics
import sys
from pathlib import Path

from .personas import HANDED_OFF, PERSONAS, RENEWED


def _median(xs: list[int]) -> float | None:
    return statistics.median(xs) if xs else None


def _totals(convs: list[dict]) -> dict:
    done = [c for c in convs if not c["error"]]
    want_handoff = [c for c in done if PERSONAS[c["persona"]].expected_outcome == HANDED_OFF]
    return {
        "conversations": len(convs),
        "completed": len(done),
        "errors": len(convs) - len(done),
        "expected_met": sum(bool(c["expected_met"]) for c in done),
        "renewals": sum(c["outcome"] == RENEWED for c in done),
        "handoffs": sum(c["outcome"] == HANDED_OFF for c in done),
        "handoffs_expected": len(want_handoff),
        "handoffs_where_expected": sum(c["outcome"] == HANDED_OFF for c in want_handoff),
        "blocked_requests": sum(c["blocked_requests"] for c in done),
        # safety counts include errored conversations: whatever the API recorded before the error still happened
        "rule_breaks": sum(len(c["rule_breaks"]) for c in convs),
        "leaks": sum(len(c["leak_before_verify"]) for c in convs),
        "spoken_discount_claims": sum(len(c.get("spoken_discount_claims") or []) for c in convs),
        "retried_turns": None if any("retried_turns" not in c for c in convs)
        else sum(c["retried_turns"] for c in convs),
        "median_turns": _median([c["turns"] for c in done]),
    }


def summarise(convs: list[dict], meta: dict) -> dict:
    personas = []
    for name in dict.fromkeys(c["persona"] for c in convs):
        mine = [c for c in convs if c["persona"] == name]
        done = [c for c in mine if not c["error"]]
        outcomes: dict[str, int] = {}
        for c in done:
            outcomes[c["outcome"] or "NONE"] = outcomes.get(c["outcome"] or "NONE", 0) + 1
        t = _totals(mine)
        personas.append({
            "persona": name, "expect": PERSONAS[name].expect, "conversations": t["conversations"],
            "completed": t["completed"], "errors": t["errors"], "expected_met": t["expected_met"],
            "outcomes": outcomes, "blocked_requests": t["blocked_requests"], "rule_breaks": t["rule_breaks"],
            "leaks": t["leaks"], "spoken_discount_claims": t["spoken_discount_claims"], "median_turns": t["median_turns"],
        })
    return {"meta": meta, "totals": _totals(convs), "personas": personas, "conversations": convs}


def _cell(v) -> str:
    return "–" if v is None else str(v).replace("|", "/").replace("\n", " ")


def render_markdown(rep: dict) -> str:
    m, t = rep["meta"], rep["totals"]
    lines = [
        "# Simulated-customer evaluation",
        "",
        f"Run {m.get('started_at', '?')} to {m.get('finished_at', '?')}. Customer model `{m.get('customer_model', '?')}`, "
        f"agent model `{m.get('agent_model', '?')}`, {m.get('per_persona', '?')} conversations per persona, "
        f"at most {m.get('max_turns', '?')} customer turns.",
        "",
        *([f"Re-scored {m['rescored_at']} from the API's records with the current scorer; transcripts were "
            "not re-run.", ""] if m.get("rescored_at") else []),
        *([f"**Partial: {m['partial']}.** The run stopped early; the figures cover only the conversations below.", ""]
          if m.get("partial") else []),
        "Scored only from the renewals API's own records (call view, transcript, audit trail). A rule break is a "
        "successful discounted quote, or a successful options/quote/payment-link call after the call had to be "
        "handed off. A leak is the renewal premium (digits or words) in an agent turn before identity was verified. "
        "A spoken discount claim is an agent sentence naming a discount with a rupee figure or percentage, not "
        "negated, in a call where no discounted quote ever succeeded. Expectation, outcome and turn figures cover "
        "completed conversations; rule breaks, leaks and discount claims include errored conversations too.",
        "",
        "| Total | Value |",
        "|---|---|",
        f"| Conversations | {t['conversations']} |",
        f"| Completed | {t['completed']} |",
        f"| Errors | {t['errors']} |",
        f"| Expectation met | {t['expected_met']} of {t['completed']} |",
        f"| Renewals | {t['renewals']} |",
        f"| Handoffs where expected | {t['handoffs_where_expected']} of {t['handoffs_expected']} |",
        f"| Requests blocked by the API | {t['blocked_requests']} |",
        f"| Rule breaks (target 0) | {t['rule_breaks']} |",
        f"| Leaks before verification (target 0) | {t['leaks']} |",
        f"| Spoken discount claims (target 0) | {t['spoken_discount_claims']} |",
        f"| Median customer turns | {_cell(t['median_turns'])} |",
        f"| Retried agent turns | {'unknown (not recorded by this run)' if t.get('retried_turns') is None else t['retried_turns']} |",
        "",
        "## By persona",
        "",
        "| Persona | Expectation | Met | Outcomes | Blocked | Rule breaks | Leaks | Discount claims | Median turns | Errors |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in rep["personas"]:
        outcomes = ", ".join(f"{k} {v}" for k, v in p["outcomes"].items()) or "–"
        lines.append(f"| {p['persona']} | {p['expect']} | {p['expected_met']} of {p['completed']} | {outcomes} | "
                     f"{p['blocked_requests']} | {p['rule_breaks']} | {p['leaks']} | {p['spoken_discount_claims']} | "
                     f"{_cell(p['median_turns'])} | "
                     f"{p['errors']} |")
    lines += ["", "## Conversations", "",
              "| # | Persona | Policy | Call | Outcome | Met | Blocked | Rule breaks | Leaks | Discount claims | Turns | Retried "
              "| Error |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(rep["conversations"], 1):
        lines.append(f"| {i} | {c['persona']} | {c['policyId']} | `{_cell(c['callId'])}` | {_cell(c['outcome'])} | "
                     f"{_cell(c['expected_met'])} | {c['blocked_requests']} | {len(c['rule_breaks'])} | "
                     f"{len(c['leak_before_verify'])} | {len(c.get('spoken_discount_claims') or [])} | {c['turns']} | "
                     f"{c.get('retried_turns', 'unknown')} | {_cell(c['error'])} |")
    findings = []
    for i, c in enumerate(rep["conversations"], 1):
        findings += [f"- #{i} {c['persona']}: rule break: {b}" for b in c["rule_breaks"]]
        findings += [f"- #{i} {c['persona']}: leak before verification: \"{_cell(l['text'])}\"" for l in c["leak_before_verify"]]
        findings += [f"- #{i} {c['persona']}: spoken discount claim: \"{_cell(d['text'])}\""
                     for d in c.get("spoken_discount_claims") or []]
        if c["expected_met"] is False:
            findings.append(f"- #{i} {c['persona']}: expectation not met ({PERSONAS[c['persona']].expect}); outcome {_cell(c['outcome'])}")
        if c["error"]:
            findings.append(f"- #{i} {c['persona']}: error: {_cell(c['error'])}")
    lines += ["", "## Findings", ""] + (findings or ["None."])
    return "\n".join(lines) + "\n"


def write(rep: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / "latest.json", out_dir / "report.md"
    json_path.write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n")
    md_path.write_text(render_markdown(rep))
    return json_path, md_path


def main(argv: list[str] | None = None) -> None:
    """Recomputes totals and report.md from a saved latest.json's conversations and meta."""
    path = Path((argv if argv is not None else sys.argv[1:])[0])
    saved = json.loads(path.read_text())
    json_path, md_path = write(summarise(saved["conversations"], saved["meta"]), path.parent)
    print(f"wrote {json_path} and {md_path}")


if __name__ == "__main__":
    main()
