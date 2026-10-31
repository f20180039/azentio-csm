"""SQLite storage: schema on start, idempotent seed, and write transactions that serialise writers."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import RESOURCES
from app.errors import ApiError
from app.vocab import CallKind, CaseStatus, Channel, FeedbackVerdict, LessonStatus, Outcome, RatingSource, sql_in

MIN_SCORE, MAX_SCORE = 1, 5

SEED_SQL = RESOURCES / "seed" / "renewal_seed.sql"

CALLS_TABLE = f"""
CREATE TABLE IF NOT EXISTS calls (
    id                       TEXT PRIMARY KEY REFERENCES cases (id),
    kind                     TEXT    NOT NULL CHECK (kind IN ({sql_in(CallKind)})),
    policy_id                TEXT REFERENCES policies (id),
    channel                  TEXT CHECK (channel IS NULL OR channel IN ({sql_in(Channel)})),
    started_at               TEXT    NOT NULL,
    ended_at                 TEXT,
    identity_verified        INTEGER NOT NULL DEFAULT 0,
    verify_failures          INTEGER NOT NULL DEFAULT 0,
    out_of_playbook_requests INTEGER NOT NULL DEFAULT 0,
    must_handoff             INTEGER NOT NULL DEFAULT 0,
    outcome                  TEXT,
    last_quote               TEXT,
    payment_link_sent        INTEGER NOT NULL DEFAULT 0,
    handoff_reason           TEXT,
    callback_at              TEXT,
    transcript               TEXT    NOT NULL DEFAULT '[]',
    CHECK (kind <> '{CallKind.RENEWAL}' OR policy_id IS NOT NULL),
    CHECK (kind <> '{CallKind.SUPPORT}' OR outcome IS NULL OR outcome IN ({sql_in(Outcome)}))
);
"""
CALLS_INDEX = "CREATE INDEX IF NOT EXISTS calls_kind_started_idx ON calls (kind, started_at DESC);"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS policies (
    id                 TEXT PRIMARY KEY,
    holder_name        TEXT    NOT NULL,
    date_of_birth      TEXT    NOT NULL,
    mobile_last4       TEXT    NOT NULL,
    product            TEXT    NOT NULL,
    sum_insured        INTEGER NOT NULL,
    expires_on         TEXT    NOT NULL,
    last_premium       INTEGER NOT NULL,
    renewal_premium    INTEGER NOT NULL,
    premium_breakdown  TEXT    NOT NULL DEFAULT '[]',
    addons             TEXT    NOT NULL DEFAULT '[]',
    claim_rejected_12m INTEGER NOT NULL DEFAULT 0,
    open_complaint     INTEGER NOT NULL DEFAULT 0,
    autodebit_failed   INTEGER NOT NULL DEFAULT 0,
    reminders_ignored  INTEGER NOT NULL DEFAULT 0,
    do_not_call        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cases (
    id             TEXT PRIMARY KEY,
    case_type      TEXT NOT NULL,
    title          TEXT NOT NULL,
    attributes     TEXT NOT NULL DEFAULT '{{}}',
    status         TEXT NOT NULL CHECK (status IN ({sql_in(CaseStatus)})),
    risk_score     REAL,
    amount_at_risk REAL,
    created_by     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

{CALLS_TABLE}
{CALLS_INDEX}

CREATE TABLE IF NOT EXISTS call_ratings (
    call_id TEXT PRIMARY KEY REFERENCES calls (id),
    score   INTEGER NOT NULL CHECK (score BETWEEN {MIN_SCORE} AND {MAX_SCORE}),
    comment TEXT,
    source  TEXT NOT NULL CHECK (source IN ({sql_in(RatingSource)})),
    author  TEXT NOT NULL,
    at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turn_feedback (
    call_id    TEXT    NOT NULL REFERENCES calls (id),
    seq        INTEGER NOT NULL,
    author     TEXT    NOT NULL,
    verdict    TEXT    NOT NULL CHECK (verdict IN ({sql_in(FeedbackVerdict)})),
    correction TEXT,
    at         TEXT    NOT NULL,
    PRIMARY KEY (call_id, seq, author)
);

CREATE TABLE IF NOT EXISTS review_resolutions (
    call_id     TEXT PRIMARY KEY REFERENCES calls (id),
    note        TEXT NOT NULL,
    resolved_by TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id             TEXT PRIMARY KEY,
    text           TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ({sql_in(LessonStatus)})),
    source_call_id TEXT REFERENCES calls (id),
    source_seq     INTEGER,
    author         TEXT NOT NULL,
    approved_by    TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lessons_status_idx ON lessons (status, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    payload    TEXT NOT NULL,
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_events_case_idx ON audit_events (case_id, id);

CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
"""


def loads(raw: str | None, default=None):
    return default if raw is None else json.loads(raw)


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.read() as con:
            con.executescript(f"BEGIN; {SCHEMA}\nCOMMIT;")
        self.widen_channel_check()
        self.seed()

    def widen_channel_check(self) -> None:
        """A database made before a channel was added still has the old CHECK on calls.channel, which SQLite cannot
        alter in place, so the table is rebuilt under the current schema with every row kept."""
        with self.read() as con:
            sql = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'calls'").fetchone()[0]
            if all(f"'{c.value}'" in sql for c in Channel):
                return
            columns = ", ".join(r["name"] for r in con.execute("PRAGMA table_info(calls)"))
            con.execute("PRAGMA foreign_keys = OFF")
            con.executescript(
                "BEGIN IMMEDIATE;"
                + CALLS_TABLE.replace("CREATE TABLE IF NOT EXISTS calls (", "CREATE TABLE calls_widened (")
                + f"INSERT INTO calls_widened ({columns}) SELECT {columns} FROM calls;"
                "DROP TABLE calls; ALTER TABLE calls_widened RENAME TO calls;"
                f"{CALLS_INDEX}\nCOMMIT;"
            )
            con.execute("PRAGMA foreign_keys = ON")

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 30000")
        return con

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        con = self.connect()
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One write transaction. An ApiError still commits, so refusals stay in the audit trail."""
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                yield con
            except ApiError:
                con.execute("COMMIT")
                raise
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")
        finally:
            con.close()

    def seed(self) -> None:
        """Upserts the synthetic renewal book generated for the Java app (ON CONFLICT DO UPDATE)."""
        sql = SEED_SQL.read_text(encoding="utf-8").replace("::jsonb", "")
        con = self.connect()
        try:
            con.executescript(f"BEGIN; {sql}\nCOMMIT;")
        finally:
            con.close()
