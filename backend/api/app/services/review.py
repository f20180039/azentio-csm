"""Customer ratings, reviewer turn feedback, the review queue, lessons and insights (shared contract, 31 Oct)."""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from app.audit import AuditLog
from app.auth import User
from app.clock import Clock
from app.db import MAX_SCORE, MIN_SCORE, Database, dumps, loads
from app.errors import ApiError
from app.services.support import MAX_LIMIT, feedback_view, find_call, rating_view, ratings_by_call, turn_view
from app.vocab import (AuditAction, CallKind, EscalationTrigger, FeedbackVerdict, LessonStatus, RatingSource,
                       ReviewReason, Role, SupportTool, TurnMetaKey, TurnRole)

LOW_RATING_MAX = 2
LESSON_MIN_CHARS, LESSON_MAX_CHARS = 10, 300
TRANSCRIPT_MIN_CHARS, TRANSCRIPT_MAX_CHARS = 1, 2000
LESSON_TARGET_STATUSES = frozenset({LessonStatus.ACTIVE, LessonStatus.RETIRED})
RATING_SOURCE_ROLE = {RatingSource.VOICE: Role.VOICE, RatingSource.PANEL: Role.ANALYST}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _optional_text(field: str, value: Any) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ApiError.bad_request(f"{field} must be a string or null")
    return value


def dissatisfied(turns: list[dict]) -> bool:
    for t in turns:
        if t.get("role") != TurnRole.AGENT:
            continue
        meta = t.get("meta") if isinstance(t.get("meta"), dict) else {}
        for step in meta.get("tool_trace") or []:
            if not isinstance(step, dict) or step.get("name") != SupportTool.ESCALATE_TO_HUMAN:
                continue
            args = step.get("args") if isinstance(step.get("args"), dict) else {}
            if args.get("trigger") == EscalationTrigger.DISSATISFIED:
                return True
    return False


def _lesson(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "text": r["text"], "status": r["status"], "sourceCallId": r["source_call_id"],
            "sourceSeq": r["source_seq"], "author": r["author"], "approvedBy": r["approved_by"],
            "createdAt": r["created_at"]}


class ReviewService:
    def __init__(self, db: Database, audit: AuditLog, clock: Clock):
        self.db = db
        self.audit = audit
        self.clock = clock

    def rate(self, call_id: str, score: Any, comment: Any, source: RatingSource, user: User) -> dict:
        if not user.has_any(RATING_SOURCE_ROLE[source]):
            raise ApiError.forbidden(f"Your role cannot record a {source} rating.")
        if not _is_int(score) or not MIN_SCORE <= score <= MAX_SCORE:
            raise ApiError.bad_request(f"score must be a whole number from {MIN_SCORE} to {MAX_SCORE}")
        comment = _optional_text("comment", comment)
        now = self.clock.instant()
        with self.db.tx() as con:
            try:
                find_call(con, call_id)
            except ApiError:
                raise ApiError.bad_request(f"Support call {call_id} not found") from None
            con.execute(
                "INSERT INTO call_ratings (call_id, score, comment, source, author, at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (call_id) DO UPDATE SET score = excluded.score, comment = excluded.comment,"
                " source = excluded.source, author = excluded.author, at = excluded.at",
                (call_id, score, comment, source, user.username, now))
            self.audit.record(con, call_id, user.username, AuditAction.RATING_RECORDED,
                              {"score": score, "comment": comment, "source": source})
            row = con.execute("SELECT * FROM call_ratings WHERE call_id = ?", (call_id,)).fetchone()
        return rating_view(row)

    def feedback(self, call_id: str, seq: int, verdict: FeedbackVerdict, correction: Any, user: User) -> dict:
        correction = _optional_text("correction", correction)
        now = self.clock.instant()
        with self.db.tx() as con:
            turns = loads(find_call(con, call_id)["transcript"], [])
            if seq < 1 or seq > len(turns):
                raise ApiError.not_found(f"Turn {seq} not found on call {call_id}")
            if turns[seq - 1].get("role") != TurnRole.AGENT:
                raise ApiError.bad_request("Feedback can only be given on agent turns")
            con.execute(
                "INSERT INTO turn_feedback (call_id, seq, author, verdict, correction, at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (call_id, seq, author) DO UPDATE SET verdict = excluded.verdict,"
                " correction = excluded.correction, at = excluded.at",
                (call_id, seq, user.username, verdict, correction, now))
            self.audit.record(con, call_id, user.username, AuditAction.FEEDBACK_RECORDED,
                              {"seq": seq, "verdict": verdict, "correction": correction})
            row = con.execute("SELECT * FROM turn_feedback WHERE call_id = ? AND seq = ? AND author = ?",
                              (call_id, seq, user.username)).fetchone()
        return feedback_view(row)

    # --- caller transcript corrections (Level 2 §6): the recognised text stays; the correction sits in meta ----

    @staticmethod
    def _caller_turn(con: sqlite3.Connection, call_id: str, seq: int) -> tuple[list[dict], dict, dict]:
        """The call's turns, the caller turn at `seq` and its meta dict (attached to the turn, ready to edit)."""
        turns = loads(find_call(con, call_id)["transcript"], [])
        if seq < 1 or seq > len(turns):
            raise ApiError.not_found(f"Turn {seq} not found on call {call_id}")
        t = turns[seq - 1]
        if t.get("role") != TurnRole.CUSTOMER:
            raise ApiError.bad_request("Transcript corrections apply to caller turns")
        meta = t.get("meta") if isinstance(t.get("meta"), dict) else {}
        t["meta"] = meta
        return turns, t, meta

    def correct_transcript(self, call_id: str, seq: int, text: Any, user: User) -> dict:
        """Shallow-merges `transcript_correction` into the turn's meta; a later correction replaces the earlier one."""
        if not isinstance(text, str) or not TRANSCRIPT_MIN_CHARS <= len(text.strip()) <= TRANSCRIPT_MAX_CHARS:
            raise ApiError.bad_request(f"text must be {TRANSCRIPT_MIN_CHARS} to {TRANSCRIPT_MAX_CHARS} characters")
        text = text.strip()
        now = self.clock.instant()
        with self.db.tx() as con:
            turns, t, meta = self._caller_turn(con, call_id, seq)
            meta[TurnMetaKey.TRANSCRIPT_CORRECTION] = {"text": text, "author": user.username, "at": now}
            con.execute("UPDATE calls SET transcript = ? WHERE id = ?", (dumps(turns), call_id))
            self.audit.record(con, call_id, user.username, AuditAction.TRANSCRIPT_CORRECTED,
                              {"seq": seq, "original": t.get("text"), "corrected": text})
        return turn_view(t)

    def clear_transcript_correction(self, call_id: str, seq: int, user: User) -> dict:
        with self.db.tx() as con:
            turns, t, meta = self._caller_turn(con, call_id, seq)
            correction = meta.get(TurnMetaKey.TRANSCRIPT_CORRECTION)
            if not isinstance(correction, dict):
                raise ApiError.not_found(f"Turn {seq} on call {call_id} has no transcript correction")
            del meta[TurnMetaKey.TRANSCRIPT_CORRECTION]
            con.execute("UPDATE calls SET transcript = ? WHERE id = ?", (dumps(turns), call_id))
            self.audit.record(con, call_id, user.username, AuditAction.TRANSCRIPT_CORRECTION_REMOVED,
                              {"seq": seq, "original": t.get("text"), "corrected": correction.get("text")})
        return turn_view(t)

    def _queue(self, con: sqlite3.Connection) -> list[dict]:
        """Every call with at least one review reason: unresolved first, then newest first."""
        ratings = ratings_by_call(con)
        bad = {r["call_id"] for r in con.execute("SELECT DISTINCT call_id FROM turn_feedback WHERE verdict = ?",
                                                 (FeedbackVerdict.BAD,))}
        resolved = {r["call_id"] for r in con.execute("SELECT call_id FROM review_resolutions")}
        items = []
        for c in con.execute("SELECT * FROM calls WHERE kind = ? ORDER BY started_at DESC, rowid DESC",
                             (CallKind.SUPPORT,)):
            rating = ratings.get(c["id"])
            reasons = []
            if rating and rating["score"] <= LOW_RATING_MAX:
                reasons.append(ReviewReason.LOW_RATING)
            if dissatisfied(loads(c["transcript"], [])):
                reasons.append(ReviewReason.DISSATISFIED)
            if c["id"] in bad:
                reasons.append(ReviewReason.BAD_FEEDBACK)
            if reasons:
                items.append({"id": c["id"], "startedAt": c["started_at"], "outcome": c["outcome"],
                              "rating": rating, "reasons": reasons, "resolved": c["id"] in resolved})
        items.sort(key=lambda i: i["resolved"])  # stable: keeps newest-first within each group
        return items

    def queue(self, limit: int) -> dict:
        if limit < 1 or limit > MAX_LIMIT:
            raise ApiError.bad_request(f"limit must be between 1 and {MAX_LIMIT}")
        with self.db.read() as con:
            return {"items": self._queue(con)[:limit]}

    def resolve(self, call_id: str, note: Any, user: User) -> dict:
        if not isinstance(note, str):
            raise ApiError.bad_request("note is required")
        now = self.clock.instant()
        with self.db.tx() as con:
            find_call(con, call_id)
            con.execute(
                "INSERT INTO review_resolutions (call_id, note, resolved_by, resolved_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (call_id) DO UPDATE SET note = excluded.note, resolved_by = excluded.resolved_by,"
                " resolved_at = excluded.resolved_at",
                (call_id, note, user.username, now))
            self.audit.record(con, call_id, user.username, AuditAction.REVIEW_RESOLVED, {"note": note})
        return {"id": call_id, "resolved": True, "note": note, "resolvedBy": user.username, "resolvedAt": now}

    def lessons(self, active: bool | None) -> dict:
        sql, params = "SELECT * FROM lessons", []
        if active:
            sql += " WHERE status = ?"
            params.append(LessonStatus.ACTIVE)
        sql += " ORDER BY created_at DESC, rowid DESC"
        with self.db.read() as con:
            return {"items": [_lesson(r) for r in con.execute(sql, params)]}

    def propose(self, text: Any, source_call_id: Any, source_seq: Any, user: User) -> dict:
        if not isinstance(text, str) or not LESSON_MIN_CHARS <= len(text.strip()) <= LESSON_MAX_CHARS:
            raise ApiError.bad_request(f"text must be {LESSON_MIN_CHARS} to {LESSON_MAX_CHARS} characters")
        text = text.strip()
        source_call_id = _optional_text("sourceCallId", source_call_id)
        if source_seq is not None and not _is_int(source_seq):
            raise ApiError.bad_request("sourceSeq must be a whole number or null")
        if source_seq is not None and source_call_id is None:
            raise ApiError.bad_request("sourceSeq needs a sourceCallId")
        lesson_id = str(uuid.uuid4())
        now = self.clock.instant()
        with self.db.tx() as con:
            if source_call_id is not None:
                c = con.execute("SELECT transcript FROM calls WHERE id = ? AND kind = ?",
                                (source_call_id, CallKind.SUPPORT)).fetchone()
                if c is None:
                    raise ApiError.bad_request(f"Support call {source_call_id} not found")
                if source_seq is not None and not 1 <= source_seq <= len(loads(c["transcript"], [])):
                    raise ApiError.bad_request(f"Turn {source_seq} not found on call {source_call_id}")
            con.execute(
                "INSERT INTO lessons (id, text, status, source_call_id, source_seq, author, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (lesson_id, text, LessonStatus.PROPOSED, source_call_id, source_seq, user.username, now, now))
            self.audit.record(con, source_call_id, user.username, AuditAction.LESSON_PROPOSED,
                              {"lessonId": lesson_id, "text": text, "status": LessonStatus.PROPOSED})
            row = con.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        return _lesson(row)

    def set_status(self, lesson_id: str, status: LessonStatus, user: User) -> dict:
        if status not in LESSON_TARGET_STATUSES:
            allowed = ", ".join(sorted(LESSON_TARGET_STATUSES))
            raise ApiError.bad_request(f"status must be one of {allowed}; got '{status}'")
        now = self.clock.instant()
        with self.db.tx() as con:
            r = con.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
            if r is None:
                raise ApiError.not_found(f"Lesson {lesson_id} not found")
            approved_by = user.username if status == LessonStatus.ACTIVE else r["approved_by"]
            con.execute("UPDATE lessons SET status = ?, approved_by = ?, updated_at = ? WHERE id = ?",
                        (status, approved_by, now, lesson_id))
            self.audit.record(con, r["source_call_id"], user.username, AuditAction.LESSON_STATUS_CHANGED,
                              {"lessonId": lesson_id, "from": r["status"], "to": status})
            row = con.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        return _lesson(row)

    def insights(self) -> dict:
        with self.db.read() as con:
            scores = [r["score"] for r in con.execute("SELECT score FROM call_ratings")]
            queue = self._queue(con)
            bad = con.execute("SELECT COUNT(*) FROM turn_feedback WHERE verdict = ?",
                              (FeedbackVerdict.BAD,)).fetchone()[0]
            active = con.execute("SELECT COUNT(*) FROM lessons WHERE status = ?",
                                 (LessonStatus.ACTIVE,)).fetchone()[0]
        distribution = {str(n): scores.count(n) for n in range(MIN_SCORE, MAX_SCORE + 1)}
        return {
            "ratings": {"count": len(scores), "average": round(sum(scores) / len(scores), 2) if scores else None,
                        "distribution": distribution},
            "lowRated": sum(1 for s in scores if s <= LOW_RATING_MAX),
            "openReviews": sum(1 for i in queue if not i["resolved"]),
            "badFeedback": bad,
            "activeLessons": active,
        }
