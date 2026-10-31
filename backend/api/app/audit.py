"""Hash-chained audit log: hash = sha256(prev | actor | action | canonical(payload) | created_at)."""
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.clock import Clock
from app.db import Database, dumps

GENESIS = "0" * 64


def _sorted(node: Any) -> Any:
    if node is None:
        return None
    if isinstance(node, dict):
        return {k: _sorted(node[k]) for k in sorted(node)}
    if isinstance(node, (list, tuple)):
        return [_sorted(n) for n in node]
    if isinstance(node, bool):
        return node
    if isinstance(node, (int, float, Decimal)):
        d = Decimal(str(node)).normalize()
        return "n:" + format(d, "f")
    return node


def canonical(payload: Any) -> str:
    return json.dumps(_sorted(payload), separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, actor: str, action: str, payload: Any, created_at: str) -> str:
    material = f"{prev_hash}|{actor}|{action}|{canonical(payload)}|{created_at}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class AuditRow:
    id: int
    case_id: str | None
    actor: str
    action: str
    payload: Any
    prev_hash: str
    hash: str
    created_at: str


def verify_chain(rows: list[AuditRow]) -> dict:
    expected_prev = GENESIS
    checked = 0
    for row in rows:
        if row.prev_hash != expected_prev:
            return {"valid": False, "checked": checked, "brokenAt": row.id,
                    "detail": "prev_hash does not match the previous event"}
        if compute_hash(row.prev_hash, row.actor, row.action, row.payload, row.created_at) != row.hash:
            return {"valid": False, "checked": checked, "brokenAt": row.id,
                    "detail": "hash does not match the event contents"}
        expected_prev = row.hash
        checked += 1
    return {"valid": True, "checked": checked, "brokenAt": None, "detail": f"All {checked} events verified"}


def _row(r: sqlite3.Row) -> AuditRow:
    return AuditRow(r["id"], r["case_id"], r["actor"], r["action"], json.loads(r["payload"]),
                    r["prev_hash"], r["hash"], r["created_at"])


class AuditLog:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock

    def record(self, con: sqlite3.Connection, case_id: str | None, actor: str, action: str,
               payload: dict | None = None) -> None:
        """Appends inside the caller's write transaction (BEGIN IMMEDIATE), so the chain never forks."""
        body = json.loads(dumps(payload or {}))
        last = con.execute("SELECT hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else GENESIS
        now = self.clock.instant()
        con.execute(
            "INSERT INTO audit_events (case_id, actor, action, payload, prev_hash, hash, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case_id, actor, str(action), dumps(body), prev, compute_hash(prev, actor, str(action), body, now), now),
        )

    def for_case(self, con: sqlite3.Connection, case_id: str) -> list[AuditRow]:
        return [_row(r) for r in con.execute("SELECT * FROM audit_events WHERE case_id = ? ORDER BY id", (case_id,))]

    def verify_all(self) -> dict:
        with self.db.read() as con:
            return verify_chain([_row(r) for r in con.execute("SELECT * FROM audit_events ORDER BY id")])
