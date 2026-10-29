"""Scores rule findings against ground truth.

    python eval/run_eval.py --truth ../samples/ground_truth.json --api http://localhost:8080 \
        --samples ../samples --case-type demo
    python eval/run_eval.py --truth ../samples/ground_truth.json --findings findings.json

ground truth and --findings files both map case_ref (the sample file name) -> [rule_id, ...].
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

TERMINAL = {"NEEDS_REVIEW", "AUTO_CLEARED", "ESCALATED", "APPROVED", "REJECTED", "FAILED"}
REPORT = Path(__file__).resolve().parent / "report.md"


def fetch_from_api(base: str, samples: Path, case_type: str, refs: list[str], auth: tuple[str, str]) -> dict:
    found: dict[str, list[str]] = {}
    with httpx.Client(base_url=base.rstrip("/"), auth=auth, timeout=60) as client:
        for ref in refs:
            with open(samples / ref, "rb") as fh:
                resp = client.post("/api/v1/cases", data={"caseType": case_type},
                                   files={"files": (ref, fh, "application/pdf")})
            resp.raise_for_status()
            case_id = resp.json()["id"]
            deadline = time.monotonic() + 120
            while True:
                case = client.get(f"/api/v1/cases/{case_id}").json()
                if case["status"] in TERMINAL or time.monotonic() > deadline:
                    break
                time.sleep(1)
            found[ref] = sorted({f["ruleId"] for f in case.get("findings", [])})
    return found


def score(truth: dict[str, list[str]], found: dict[str, list[str]]) -> tuple[dict, dict]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for ref, expected in truth.items():
        exp, got = set(expected), set(found.get(ref, []))
        for rule in exp & got:
            counts[rule]["tp"] += 1
        for rule in got - exp:
            counts[rule]["fp"] += 1
        for rule in exp - got:
            counts[rule]["fn"] += 1

    def prf(c: dict[str, int]) -> dict:
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 1.0
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 1.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        return {**c, "precision": p, "recall": r, "f1": f1}

    per_rule = {rule: prf(c) for rule, c in sorted(counts.items())}
    total = {k: sum(c[k] for c in counts.values()) for k in ("tp", "fp", "fn")}
    return per_rule, prf(total)


def render(per_rule: dict, overall: dict, n_cases: int) -> str:
    rows = ["| Rule | TP | FP | FN | Precision | Recall | F1 |", "|---|---|---|---|---|---|---|"]
    for rule, m in [*per_rule.items(), ("**Overall (micro)**", overall)]:
        rows.append(f"| {rule} | {m['tp']} | {m['fp']} | {m['fn']} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} |")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    return f"# Evaluation report\n\n{n_cases} cases, run {stamp}.\n\n" + "\n".join(rows) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True, type=Path)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--findings", type=Path)
    src.add_argument("--api")
    ap.add_argument("--samples", type=Path, default=Path(__file__).resolve().parents[2] / "samples")
    ap.add_argument("--case-type", default="demo")
    ap.add_argument("--user", default="analyst:analyst")
    args = ap.parse_args()

    truth = json.loads(args.truth.read_text())
    if args.findings:
        found = json.loads(args.findings.read_text())
    else:
        user, _, password = args.user.partition(":")
        found = fetch_from_api(args.api, args.samples, args.case_type, list(truth), (user, password))

    per_rule, overall = score(truth, found)
    report = render(per_rule, overall, len(truth))
    REPORT.write_text(report)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
