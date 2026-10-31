"""One-off backfill: marks the calls of a saved evaluation run as simulated, so the dashboard leaves them out.

  cd voice && .venv/bin/python -m eval.tag_simulated eval/out/latest.json
Needs the renewals API running; uses the admin account (the endpoint is admin-only).
"""
import argparse
import json
import sys
from pathlib import Path

import httpx


def call_ids(report: dict) -> list[str]:
    return list(dict.fromkeys(c["callId"] for c in report.get("conversations", []) if c.get("callId")))


def tag(ids: list[str], client: httpx.Client) -> int:
    resp = client.post("/api/v1/renewals/calls/mark-simulated", json={"callIds": ids})
    resp.raise_for_status()
    return resp.json()["marked"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report", type=Path, nargs="?", default=Path(__file__).resolve().parent / "out" / "latest.json")
    ap.add_argument("--api", default="http://localhost:8080")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin")
    args = ap.parse_args(argv)
    ids = call_ids(json.loads(args.report.read_text()))
    if not ids:
        print("no call ids in the report")
        return 1
    with httpx.Client(base_url=args.api.rstrip("/"), auth=(args.user, args.password), timeout=30) as client:
        marked = tag(ids, client)
    print(f"marked {marked} of {len(ids)} calls as simulated")
    return 0 if marked == len(ids) else 2


if __name__ == "__main__":
    sys.exit(main())
