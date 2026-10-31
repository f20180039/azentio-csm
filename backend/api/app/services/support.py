"""Support call records (shared contract): turns live in the call's transcript as {seq, role, text, at, meta}."""
from __future__ import annotations

import sqlite3
import uuid
from enum import StrEnum
from typing import Any, TypeVar

from app.audit import AuditLog
from app.clock import Clock
from app.db import Database, dumps, loads
from app.errors import ApiError
from app.vocab import AuditAction, CallKind, CaseStatus, CaseType, Channel, ErrorCode, OpOutcome, Outcome, TurnRole

MAX_LIMIT = 200
E = TypeVar("E", bound=StrEnum)


def parse(enum: type[E], field: str, value: Any) -> E:
    """Validates a vocabulary value at the boundary; unknown values are a 400 naming the allowed set."""
    if isinstance(value, str):
        try:
            return enum(value)
        except ValueError:
            pass
    allowed = ", ".join(v.value for v in enum)
    got = "" if value is None else f"; got '{value}'"
    raise ApiError.bad_request(f"{field} must be one of {allowed}{got}")


def verified(turns: list[dict]) -> bool:
    return any(t.get("role") == TurnRole.CUSTOMER and (t.get("meta") or {}).get("verified") is True for t in turns)


def intents(turns: list[dict]) -> list[str]:
    out: dict[str, None] = {}
    for t in turns:
        if t.get("role") == TurnRole.CUSTOMER:
            for i in (t.get("meta") or {}).get("intents") or []:
                if isinstance(i, str):
                    out.setdefault(i, None)
    return list(out)


def failed_ops(turns: list[dict]) -> int:
    """Tool calls that FAILED across the call's agent turns; entries without an outcome (older calls) count as none."""
    count = 0
    for t in turns:
        for entry in (t.get("meta") or {}).get("tool_trace") or []:
            if isinstance(entry, dict) and entry.get("outcome") == OpOutcome.FAILED:
                count += 1
    return count


def _turn(t: dict) -> dict:
    meta = t.get("meta")
    return {"seq": t.get("seq"), "role": t.get("role"), "text": t.get("text"), "at": t.get("at"),
            "meta": meta if isinstance(meta, dict) else {}}


def rating_view(r: sqlite3.Row) -> dict:
    return {"score": r["score"], "comment": r["comment"], "source": r["source"], "at": r["at"]}


def feedback_view(r: sqlite3.Row) -> dict:
    return {"seq": r["seq"], "verdict": r["verdict"], "correction": r["correction"], "author": r["author"],
            "at": r["at"]}


def ratings_by_call(con: sqlite3.Connection) -> dict[str, dict]:
    return {r["call_id"]: rating_view(r) for r in con.execute("SELECT * FROM call_ratings")}


def find_call(con: sqlite3.Connection, call_id: str) -> sqlite3.Row:
    c = con.execute("SELECT * FROM calls WHERE id = ? AND kind = ?", (call_id, CallKind.SUPPORT)).fetchone()
    if c is None:
        raise ApiError.not_found(f"Support call {call_id} not found")
    return c


class SupportService:
    def __init__(self, db: Database, audit: AuditLog, clock: Clock):
        self.db = db
        self.audit = audit
        self.clock = clock

    def start(self, channel: Channel, actor: str) -> dict:
        call_id = str(uuid.uuid4())
        now = self.clock.instant()
        with self.db.tx() as con:
            con.execute(
                "INSERT INTO cases (id, case_type, title, attributes, status, created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (call_id, CaseType.SUPPORT_CALL, f"Support call · {channel}", dumps({"channel": channel}),
                 CaseStatus.PROCESSING, actor, now, now))
            con.execute("INSERT INTO calls (id, kind, channel, started_at) VALUES (?, ?, ?, ?)",
                        (call_id, CallKind.SUPPORT, channel, now))
            self.audit.record(con, call_id, actor, AuditAction.CALL_STARTED,
                              {"kind": CallKind.SUPPORT, "channel": channel})
        return {"id": call_id}

    def add_turn(self, call_id: str, role: TurnRole, text: str | None, at: str | None, meta: Any) -> dict:
        if text is None:
            raise ApiError.bad_request("text is required")
        if meta is not None and not isinstance(meta, dict):
            raise ApiError.bad_request("meta must be a JSON object")
        with self.db.tx() as con:
            c = self._find(con, call_id)
            if c["ended_at"] is not None:
                raise ApiError.conflict(ErrorCode.CALL_ENDED)
            turns = loads(c["transcript"], [])
            seq = len(turns) + 1
            turns.append({"seq": seq, "role": role, "text": text, "at": at or self.clock.instant(),
                          "meta": dict(meta or {})})
            con.execute("UPDATE calls SET transcript = ? WHERE id = ?", (dumps(turns), call_id))
        return {"seq": seq}

    def patch_meta(self, call_id: str, seq: int, patch: Any) -> dict:
        """Shallow merge; allowed after the call ends (intents are back-filled by the classifier)."""
        if not isinstance(patch, dict):
            raise ApiError.bad_request("meta patch must be a JSON object")
        with self.db.tx() as con:
            c = self._find(con, call_id)
            turns = loads(c["transcript"], [])
            if seq < 1 or seq > len(turns):
                raise ApiError.not_found(f"Turn {seq} not found on call {call_id}")
            t = turns[seq - 1]
            meta = t.get("meta") if isinstance(t.get("meta"), dict) else {}
            meta.update(patch)
            t["meta"] = meta
            con.execute("UPDATE calls SET transcript = ? WHERE id = ?", (dumps(turns), call_id))
        return _turn(t)

    def end(self, call_id: str, outcome: Outcome, actor: str) -> dict:
        now = self.clock.instant()
        with self.db.tx() as con:
            c = self._find(con, call_id)
            if c["ended_at"] is not None:
                raise ApiError.conflict(ErrorCode.CALL_ALREADY_ENDED)
            con.execute("UPDATE calls SET outcome = ?, ended_at = ? WHERE id = ?", (outcome, now, call_id))
            status = CaseStatus.ESCALATED if outcome == Outcome.ESCALATED else CaseStatus.NEEDS_REVIEW
            con.execute("UPDATE cases SET status = ?, updated_at = ? WHERE id = ?", (status, now, call_id))
            self.audit.record(con, call_id, actor, AuditAction.CALL_ENDED,
                              {"outcome": outcome, "turnCount": len(loads(c["transcript"], []))})
        return {"id": call_id, "outcome": outcome, "endedAt": now}

    def get(self, call_id: str) -> dict:
        with self.db.read() as con:
            c = self._find(con, call_id)
            rating = con.execute("SELECT * FROM call_ratings WHERE call_id = ?", (call_id,)).fetchone()
            feedback: dict[int, list[dict]] = {}
            for f in con.execute("SELECT * FROM turn_feedback WHERE call_id = ? ORDER BY at, author", (call_id,)):
                feedback.setdefault(f["seq"], []).append(feedback_view(f))
        turns = loads(c["transcript"], [])
        return {"id": c["id"], "channel": c["channel"], "startedAt": c["started_at"], "endedAt": c["ended_at"],
                "outcome": c["outcome"], "verified": verified(turns),
                "rating": rating_view(rating) if rating else None,
                "turns": [{**_turn(t), "feedback": feedback.get(t.get("seq"), [])} for t in turns]}

    def list(self, outcome: Outcome | None, limit: int) -> dict:
        if limit < 1 or limit > MAX_LIMIT:
            raise ApiError.bad_request(f"limit must be between 1 and {MAX_LIMIT}")
        sql = "SELECT * FROM calls WHERE kind = ?"
        params: list[Any] = [CallKind.SUPPORT]
        if outcome is not None:
            sql += " AND outcome = ?"
            params.append(outcome)
        sql += " ORDER BY started_at DESC, rowid DESC LIMIT ?"
        params.append(limit)
        with self.db.read() as con:
            rows = con.execute(sql, params).fetchall()
            ratings = ratings_by_call(con)
        items = []
        for c in rows:
            turns = loads(c["transcript"], [])
            items.append({"id": c["id"], "channel": c["channel"], "startedAt": c["started_at"],
                          "endedAt": c["ended_at"], "outcome": c["outcome"], "verified": verified(turns),
                          "turnCount": len(turns), "intents": intents(turns), "rating": ratings.get(c["id"]),
                          "failedOps": failed_ops(turns)})
        return {"items": items}

    def _find(self, con: sqlite3.Connection, call_id: str) -> sqlite3.Row:
        return find_call(con, call_id)
