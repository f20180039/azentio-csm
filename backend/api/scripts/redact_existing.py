"""One-off: rewrite support transcripts and reviewer corrections stored before PII redaction existed.

Runs every turn's text and meta, and every turn_feedback correction, through the same `Redactor` the API uses,
so the calls database holds only `[KIND#n]` tokens and the values move to the PII vault. Safe to run again:
already-redacted rows contain nothing to find and are left untouched.

    cd backend/api && .venv/bin/python scripts/redact_existing.py        # reads API_DB_PATH, PII_VAULT_PATH, PII_VAULT_KEY
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clock import Clock  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import Database, dumps, loads  # noqa: E402
from app.pii import Redactor  # noqa: E402
from app.pii_vault import PiiVault  # noqa: E402
from app.vocab import CallKind  # noqa: E402


def redact_all(db: Database, vault: PiiVault, today: date) -> dict[str, int]:
    """Returns how many calls, turns and corrections changed; a second run returns zeros."""
    changed = {"calls": 0, "turns": 0, "feedback": 0}
    with db.tx() as con:
        calls = con.execute("SELECT id, transcript FROM calls WHERE kind = ? ORDER BY rowid",
                            (CallKind.SUPPORT,)).fetchall()
        for c in calls:
            redactor = Redactor(vault, c["id"], today)
            turns = loads(c["transcript"], [])
            touched = 0
            for t in turns:
                before = dumps(t)
                if isinstance(t.get("text"), str):
                    t["text"] = redactor.redact(t["text"])
                if isinstance(t.get("meta"), dict):
                    t["meta"] = redactor.redact(t["meta"])
                touched += dumps(t) != before
            if touched:
                con.execute("UPDATE calls SET transcript = ? WHERE id = ?", (dumps(turns), c["id"]))
                changed["calls"] += 1
                changed["turns"] += touched
            for f in con.execute("SELECT seq, author, correction FROM turn_feedback WHERE call_id = ?",
                                 (c["id"],)).fetchall():
                if not isinstance(f["correction"], str):
                    continue
                redacted = redactor.redact(f["correction"])
                if redacted != f["correction"]:
                    con.execute("UPDATE turn_feedback SET correction = ? WHERE call_id = ? AND seq = ? AND author = ?",
                                (redacted, c["id"], f["seq"], f["author"]))
                    changed["feedback"] += 1
    return changed


def main() -> None:
    settings = Settings.from_env()
    clock = Clock()
    if not settings.pii_vault_key:
        print("PII_VAULT_KEY is not set: values will be tokenised but not kept in the vault", file=sys.stderr)
    vault = PiiVault(settings.pii_vault_path, settings.pii_vault_key, clock.instant)
    result = redact_all(Database(settings.db_path), vault, clock.today())
    print(f"redacted {result['turns']} turn(s) across {result['calls']} call(s) and {result['feedback']} correction(s)")


if __name__ == "__main__":
    main()
