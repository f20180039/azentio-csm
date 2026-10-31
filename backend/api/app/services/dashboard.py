"""Read-only aggregates for the Renewal Desk dashboard and /stats, all computed from stored rows."""
import json
from datetime import date, datetime, timedelta

from app.audit import AuditLog
from app.clock import Clock
from app.db import Database, dumps, loads
from app.errors import ApiError
from app.lapse_risk import assess
from app.vocab import GUARDRAIL_ACTIONS, AuditAction, CallKind, CaseType, RenewalOutcome, Route

DAYS = 7
BANDS = 5
RECENT_LIMIT = 20
GUARDRAIL_LIMIT = 30

# Bound flag: 1 lets simulated calls through, 0 keeps only real ones.
REAL_OR_ALL = "(? OR COALESCE(json_extract(k.attributes, '$.simulated'), 0) = 0)"


def _guardrail_detail(action: str, payload: dict) -> str | None:
    if action == AuditAction.TOOL_REFUSED:
        return payload.get("code")
    if action == AuditAction.TOOL_HANDOFF_TO_HUMAN:
        return payload.get("reason")
    if action == AuditAction.RULE_OUTSIDE_PLAYBOOK:
        return f"Asked for {payload.get('requestedDiscountPercent')}% discount, limit {payload.get('maxDiscountPercent')}%"
    if action == AuditAction.IDENTITY_FAILED:
        return f"Attempt {payload.get('attempt')}"
    return None


class DashboardService:
    def __init__(self, db: Database, audit: AuditLog, clock: Clock):
        self.db = db
        self.audit = audit
        self.clock = clock

    def dashboard(self, include_simulated: bool) -> dict:
        today = self.clock.today()
        start_of_today = datetime.combine(today, datetime.min.time(), self.clock.zone)
        flag = int(include_simulated)
        with self.db.read() as con:
            calls = con.execute(
                f"""SELECT c.*, p.holder_name, p.product FROM calls c
                    JOIN cases k ON k.id = c.id JOIN policies p ON p.id = c.policy_id
                    WHERE c.kind = ? AND k.case_type = ? AND {REAL_OR_ALL}
                    ORDER BY c.started_at DESC, c.rowid DESC""",
                (CallKind.RENEWAL, CaseType.RENEWAL_CALL, flag)).fetchall()
            marks = ", ".join("?" for _ in GUARDRAIL_ACTIONS)
            events = con.execute(
                f"""SELECT a.* , p.holder_name FROM audit_events a
                    JOIN cases k ON k.id = a.case_id AND k.case_type = ?
                    JOIN calls c ON c.id = a.case_id AND c.kind = ?
                    JOIN policies p ON p.id = c.policy_id
                    WHERE a.action IN ({marks}) AND {REAL_OR_ALL}
                    ORDER BY a.created_at DESC, a.id DESC""",
                (CaseType.RENEWAL_CALL, CallKind.RENEWAL, *GUARDRAIL_ACTIONS, flag)).fetchall()
            policies = con.execute("SELECT * FROM policies").fetchall()

        def started_today(c) -> bool:
            return datetime.fromisoformat(c["started_at"]) >= start_of_today

        ended = [c for c in calls if c["ended_at"] is not None]
        renewed = [c for c in calls if c["outcome"] == RenewalOutcome.RENEWAL_PENDING_PAYMENT]
        retained = sum(int((loads(c["last_quote"]) or {}).get("annualPremium") or 0) for c in renewed)
        counts = {a: 0 for a in GUARDRAIL_ACTIONS}
        for e in events:
            counts[e["action"]] = counts.get(e["action"], 0) + 1

        tally = [{r: 0 for r in Route} for _ in range(BANDS)]
        at_risk = 0
        for p in policies:
            if date.fromisoformat(p["expires_on"]) < today:
                continue
            r = assess(dict(p), today)
            tally[min(BANDS - 1, int(r.score * BANDS))][r.route] += 1
            if r.route != Route.REMINDER_SMS:
                at_risk += int(p["renewal_premium"])
        bands = [{"band": f"{i * 0.2:.1f}–{(i + 1) * 0.2:.1f}", "count": sum(t.values()),
                  "agentCall": t[Route.AGENT_CALL], "humanOnly": t[Route.HUMAN_ONLY],
                  "reminderSms": t[Route.REMINDER_SMS]} for i, t in enumerate(tally)]

        kpis = {
            "callsToday": sum(1 for c in calls if started_today(c)),
            "callsTotal": len(calls),
            "inProgress": sum(1 for c in calls if c["outcome"] is None),
            "renewed": len(renewed),
            "handedOff": sum(1 for c in calls if c["outcome"] == RenewalOutcome.HANDED_OFF),
            "noDecision": sum(1 for c in calls if c["outcome"] == RenewalOutcome.NO_DECISION),
            "premiumRetained": retained,
            "premiumAtRisk": at_risk,
            "blockedRequests": counts[AuditAction.RULE_OUTSIDE_PLAYBOOK],
            "refusals": counts[AuditAction.TOOL_REFUSED],
            "identityFailures": counts[AuditAction.IDENTITY_FAILED],
            "saveRate": len(renewed) / len(ended) if ended else 0.0,
        }
        return {
            "kpis": kpis,
            "outcomesByDay": self._by_day(ended, today),
            "recentCalls": [{
                "callId": c["id"], "holderName": c["holder_name"], "policyId": c["policy_id"],
                "product": c["product"], "startedAt": c["started_at"], "endedAt": c["ended_at"],
                "outcome": c["outcome"], "mustHandoff": bool(c["must_handoff"]),
                "outOfPlaybookRequests": c["out_of_playbook_requests"],
            } for c in calls[:RECENT_LIMIT]],
            "guardrailEvents": [{
                "at": e["created_at"], "callId": e["case_id"], "holderName": e["holder_name"],
                "action": e["action"], "detail": _guardrail_detail(e["action"], json.loads(e["payload"])),
            } for e in events[:GUARDRAIL_LIMIT]],
            "riskBands": bands,
        }

    def _by_day(self, ended, today: date) -> list[dict]:
        first = today - timedelta(days=DAYS - 1)
        days = {first + timedelta(days=i): {"renewed": 0, "handedOff": 0, "noDecision": 0} for i in range(DAYS)}
        for c in ended:
            if c["outcome"] is None:
                continue
            d = datetime.fromisoformat(c["ended_at"]).astimezone(self.clock.zone).date()
            if d not in days:
                continue
            key = {RenewalOutcome.RENEWAL_PENDING_PAYMENT: "renewed",
                   RenewalOutcome.HANDED_OFF: "handedOff"}.get(c["outcome"], "noDecision")
            days[d][key] += 1
        return [{"day": d.isoformat(), **v} for d, v in days.items()]

    def mark_simulated(self, call_ids: list[str] | None, actor: str) -> int:
        if not call_ids:
            raise ApiError.bad_request("callIds is required")
        marked = 0
        with self.db.tx() as con:
            for cid in call_ids:
                row = con.execute("SELECT attributes FROM cases WHERE id = ? AND case_type = ?",
                                  (str(cid), CaseType.RENEWAL_CALL)).fetchone()
                if row is None:
                    continue
                attrs = {**(loads(row["attributes"], {}) or {}), "simulated": True}
                con.execute("UPDATE cases SET attributes = ? WHERE id = ?", (dumps(attrs), str(cid)))
                marked += 1
            self.audit.record(con, None, actor, AuditAction.CALLS_MARKED_SIMULATED,
                              {"callIds": [str(c) for c in call_ids], "marked": marked})
        return marked

    def stats(self, include_simulated: bool) -> dict:
        """Counts by case status from stored cases; simulated renewal calls only when asked for."""
        with self.db.read() as con:
            rows = con.execute(
                f"""SELECT k.status, count(*) AS n FROM cases k
                    WHERE {REAL_OR_ALL} GROUP BY k.status ORDER BY k.status""", (int(include_simulated),)).fetchall()
            kinds = con.execute(
                f"""SELECT c.kind, count(*) AS n FROM calls c JOIN cases k ON k.id = c.id
                    WHERE {REAL_OR_ALL} GROUP BY c.kind""", (int(include_simulated),)).fetchall()
        by_kind = {k: 0 for k in CallKind}
        by_kind.update({r["kind"]: r["n"] for r in kinds})
        return {"byStatus": {r["status"]: r["n"] for r in rows},
                "renewalCalls": by_kind[CallKind.RENEWAL], "supportCalls": by_kind[CallKind.SUPPORT]}
