"""Cases: every renewal and support call is a case; reviewers decide them (four-eyes), and decisions are audited."""
from __future__ import annotations

import sqlite3
from typing import Any

from app.audit import AuditLog
from app.clock import Clock
from app.db import Database, loads
from app.errors import ApiError
from app.vocab import CASE_ACTION_STATUS, CASE_DECISION_AUDIT, REVIEWABLE, CaseAction, CaseStatus

MAX_PAGE_SIZE = 100


def _summary(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "caseType": r["case_type"], "title": r["title"], "attributes": loads(r["attributes"], {}),
            "status": r["status"], "riskScore": r["risk_score"], "amountAtRisk": r["amount_at_risk"],
            "createdBy": r["created_by"], "createdAt": r["created_at"], "updatedAt": r["updated_at"],
            "documentCount": 0, "openFindings": 0}


class CaseService:
    def __init__(self, db: Database, audit: AuditLog, clock: Clock):
        self.db = db
        self.audit = audit
        self.clock = clock

    def list(self, status: CaseStatus | None, case_type: str | None, page: int, size: int) -> dict:
        page = max(0, page)
        size = min(max(1, size), MAX_PAGE_SIZE)
        where, params = [], []
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if case_type:
            where.append("case_type = ?")
            params.append(case_type)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        with self.db.read() as con:
            total = con.execute(f"SELECT count(*) FROM cases{clause}", params).fetchone()[0]
            rows = con.execute(
                f"""SELECT * FROM cases{clause}
                    ORDER BY risk_score IS NULL, risk_score DESC, amount_at_risk IS NULL, amount_at_risk DESC,
                             created_at DESC LIMIT ? OFFSET ?""", (*params, size, page * size)).fetchall()
        # Spring Page shape, which the web app's normalisePage reads.
        return {"content": [_summary(r) for r in rows], "totalElements": total,
                "totalPages": (total + size - 1) // size, "number": page, "size": size}

    def get(self, case_id: str) -> dict:
        with self.db.read() as con:
            return self._detail(con, case_id)

    def decide(self, case_id: str, action: Any, reason: str | None, user: str) -> dict:
        with self.db.tx() as con:
            c = self._load(con, case_id)
            if c["created_by"] == user:
                raise ApiError.forbidden("Four-eyes rule: you started this case, so another reviewer must decide it.")
            if c["status"] not in REVIEWABLE:
                raise ApiError.conflict(f"Case is {c['status']}. Decisions are possible once it is "
                                        "NEEDS_REVIEW, ESCALATED or AUTO_CLEARED.")
            try:
                act = CaseAction(str(action or "").strip().upper())
            except ValueError as e:
                raise ApiError.bad_request("action must be APPROVE, REJECT or ESCALATE.") from e
            if not reason or not reason.strip():
                raise ApiError.bad_request("Give a reason for the decision. It goes into the audit trail.")
            nxt = CASE_ACTION_STATUS[act]
            if nxt == CaseStatus.ESCALATED and c["status"] == CaseStatus.ESCALATED:
                raise ApiError.conflict("This case is already escalated.")
            con.execute("UPDATE cases SET status = ?, updated_at = ? WHERE id = ?",
                        (nxt, self.clock.instant(), case_id))
            self.audit.record(con, case_id, user, CASE_DECISION_AUDIT[act],
                              {"from": c["status"], "to": nxt, "reason": reason})
            return self._detail(con, case_id)

    def audit_for(self, case_id: str) -> list[dict]:
        with self.db.read() as con:
            self._load(con, case_id)
            return [{"id": r.id, "caseId": r.case_id, "actor": r.actor, "action": r.action, "payload": r.payload,
                     "prevHash": r.prev_hash, "hash": r.hash, "createdAt": r.created_at}
                    for r in self.audit.for_case(con, case_id)]

    def _load(self, con, case_id: str) -> sqlite3.Row:
        r = con.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if r is None:
            raise ApiError.not_found(f"Case {case_id} does not exist.")
        return r

    def _detail(self, con, case_id: str) -> dict:
        return {**_summary(self._load(con, case_id)), "documents": [], "findings": [], "extractions": []}
