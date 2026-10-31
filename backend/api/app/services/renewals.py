"""Renewal calls: every playbook limit is enforced here, not in the voice agent (port of RenewalService.java)."""
import math
import re
import sqlite3
import uuid
from datetime import date, time
from decimal import ROUND_HALF_UP, Decimal

from app.audit import AuditLog
from app.clock import Clock
from app.db import Database, dumps, loads
from app.errors import ApiError
from app.lapse_risk import assess
from app.playbook import Playbook
from app.vocab import (SUMMARY_STATEMENTS, AuditAction, CallKind, CaseStatus, CaseType, DeliveryChannel, ErrorCode,
                       PaymentPlanInstalments, RenewalOutcome, Tool, TurnRole)

CALLS_FROM = time(9, 0)
CALLS_UNTIL = time(21, 0)
DOB_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RenewalService:
    def __init__(self, db: Database, audit: AuditLog, playbook: Playbook, clock: Clock, enforce_calling_hours: bool):
        self.db = db
        self.audit = audit
        self.playbook = playbook
        self.clock = clock
        self.enforce_calling_hours = enforce_calling_hours

    # ---- staff ----

    def queue(self) -> list[dict]:
        today = self.clock.today()
        items = []
        with self.db.read() as con:
            for p in con.execute("SELECT * FROM policies"):
                expires = date.fromisoformat(p["expires_on"])
                if expires < today:
                    continue
                r = assess(dict(p), today)
                items.append({
                    "policyId": p["id"], "holderName": p["holder_name"], "product": p["product"],
                    "expiresOn": p["expires_on"], "daysToExpiry": (expires - today).days, "score": r.score,
                    "signals": [s.to_json() for s in r.signals], "route": r.route,
                })
        items.sort(key=lambda q: (-q["score"], q["daysToExpiry"]))
        return items

    def start_call(self, policy_id: str | None, simulated: bool, actor: str) -> dict:
        if not policy_id or not policy_id.strip():
            raise ApiError.bad_request("policyId is required")
        with self.db.tx() as con:
            p = con.execute("SELECT * FROM policies WHERE id = ?", (policy_id,)).fetchone()
            if p is None:
                raise ApiError.not_found(f"Policy {policy_id} not found")
            if p["open_complaint"]:
                raise ApiError.conflict(ErrorCode.HUMAN_ONLY)
            if p["do_not_call"]:
                raise ApiError.conflict(ErrorCode.DO_NOT_CALL)
            if self.enforce_calling_hours:
                now = self.clock.now().time()
                if now < CALLS_FROM or now >= CALLS_UNTIL:
                    raise ApiError.conflict(ErrorCode.OUTSIDE_CALLING_HOURS)
            call_id = str(uuid.uuid4())
            now_iso = self.clock.instant()
            attributes = {"policyId": p["id"], "simulated": True} if simulated else {"policyId": p["id"]}
            con.execute(
                "INSERT INTO cases (id, case_type, title, attributes, status, created_by, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (call_id, CaseType.RENEWAL_CALL, f"Renewal call · {p['holder_name']}", dumps(attributes),
                 CaseStatus.PROCESSING, actor, now_iso, now_iso))
            con.execute("INSERT INTO calls (id, kind, policy_id, started_at) VALUES (?, ?, ?, ?)",
                        (call_id, CallKind.RENEWAL, p["id"], now_iso))
            self.audit.record(con, call_id, actor, AuditAction.CALL_STARTED,
                              {"policyId": p["id"], "playbook": self.playbook.id,
                               "playbookVersion": self.playbook.version})
            return {"callId": call_id, "caseId": call_id, "greeting": self._greeting(p)}

    def get_call(self, call_id: str) -> dict:
        with self.db.read() as con:
            c = self._find(con, call_id)
            p = self._policy(con, c)
            transcript = loads(c["transcript"], [])
            summary = []
            for row in self.audit.for_case(con, call_id):
                if row.action in SUMMARY_STATEMENTS:
                    up_to = int(row.payload.get("turnIndex") or 0)
                    summary.append({"statement": SUMMARY_STATEMENTS[AuditAction(row.action)],
                                    "quote": _last_customer_turn(transcript, up_to)})
            return {
                "callId": c["id"], "caseId": c["id"], "policyId": c["policy_id"], "holderName": p["holder_name"],
                "greeting": self._greeting(p), "identityVerified": bool(c["identity_verified"]),
                "verifyFailures": c["verify_failures"], "outOfPlaybookRequests": c["out_of_playbook_requests"],
                "mustHandoff": bool(c["must_handoff"]), "outcome": c["outcome"],
                "lastQuote": loads(c["last_quote"]), "paymentLinkSent": bool(c["payment_link_sent"]),
                "handoffReason": c["handoff_reason"], "callbackAt": c["callback_at"], "transcript": transcript,
                "summary": summary,
            }

    # ---- voice agent tools ----

    def verify(self, call_id: str, date_of_birth: str | None, actor: str) -> dict:
        max_fail = self.playbook.max_verify_failures
        with self.db.tx() as con:
            c = self._open_call(con, call_id, Tool.VERIFY, actor)
            if c["verify_failures"] >= max_fail:
                raise self._refused(con, call_id, actor, Tool.VERIFY, ApiError.conflict(ErrorCode.VERIFY_LOCKED))
            dob = _parse_dob(date_of_birth)
            if c["identity_verified"]:
                self.audit.record(con, call_id, actor, AuditAction.TOOL_REFUSED,
                                  {"tool": Tool.VERIFY, "code": ErrorCode.ALREADY_VERIFIED})
                return {"verified": True, "attemptsLeft": max_fail - c["verify_failures"],
                        "mustHandoff": bool(c["must_handoff"])}
            p = self._policy(con, c)
            failures, must, verified = c["verify_failures"], bool(c["must_handoff"]), False
            if date.fromisoformat(p["date_of_birth"]) == dob:
                verified = True
                con.execute("UPDATE calls SET identity_verified = 1 WHERE id = ?", (call_id,))
                self.audit.record(con, call_id, actor, AuditAction.IDENTITY_VERIFIED, {"attempt": failures + 1})
            else:
                failures += 1
                must = must or failures >= max_fail
                con.execute("UPDATE calls SET verify_failures = ?, must_handoff = ? WHERE id = ?",
                            (failures, int(must), call_id))
                self.audit.record(con, call_id, actor, AuditAction.IDENTITY_FAILED,
                                  {"attempt": failures, "mustHandoff": must})
            return {"verified": verified, "attemptsLeft": max_fail - failures, "mustHandoff": must}

    def policy(self, call_id: str, actor: str) -> dict:
        with self.db.tx() as con:
            c = self._verified_call(con, call_id, Tool.GET_POLICY, actor)
            p = self._policy(con, c)
            self.audit.record(con, call_id, actor, AuditAction.TOOL_GET_POLICY, {"policyId": p["id"]})
            return {
                "policyId": p["id"], "product": p["product"], "sumInsured": int(p["sum_insured"]),
                "expiresOn": p["expires_on"], "lastPremium": int(p["last_premium"]),
                "renewalPremium": int(p["renewal_premium"]), "breakdown": loads(p["premium_breakdown"], []),
                "addons": loads(p["addons"], []), "mobileLast4": p["mobile_last4"],
                "mustHandoff": bool(c["must_handoff"]),
            }

    def options(self, call_id: str, actor: str) -> dict:
        with self.db.tx() as con:
            c = self._offerable_call(con, call_id, Tool.LIST_ALLOWED_OPTIONS, actor)
            removable = []
            if self.playbook.removable_optional_addons:
                for a in loads(self._policy(con, c)["addons"], []):
                    if a.get("optional"):
                        removable.append({"code": a.get("code"), "name": a.get("name"),
                                          "saving": int(a.get("premium") or 0)})
            self.audit.record(con, call_id, actor, AuditAction.TOOL_LIST_ALLOWED_OPTIONS,
                              {"removable": len(removable)})
            return {"paymentPlans": list(self.playbook.payment_plans), "removableAddons": removable,
                    "maxDiscountPercent": self.playbook.max_discount_percent, "mustHandoff": bool(c["must_handoff"])}

    def quote(self, call_id: str, drop_addons: list[str] | None, plan: str | None, discount: int | None,
              actor: str) -> dict:
        pb = self.playbook
        with self.db.tx() as con:
            c = self._offerable_call(con, call_id, Tool.QUOTE_RENEWAL, actor)
            p = self._policy(con, c)
            drop = list(dict.fromkeys(drop_addons or []))
            discount = 0 if discount is None else discount
            if discount > pb.max_discount_percent:
                count = c["out_of_playbook_requests"] + 1
                must = bool(c["must_handoff"]) or count >= pb.max_out_of_playbook_requests
                con.execute("UPDATE calls SET out_of_playbook_requests = ?, must_handoff = ? WHERE id = ?",
                            (count, int(must), call_id))
                self.audit.record(con, call_id, actor, AuditAction.RULE_OUTSIDE_PLAYBOOK, {
                    "requestedDiscountPercent": discount, "maxDiscountPercent": pb.max_discount_percent,
                    "count": count, "mustHandoff": must, "turnIndex": _turn_count(c)})
                raise ApiError.invalid_option(ErrorCode.OUTSIDE_PLAYBOOK)
            if plan is None or plan not in pb.payment_plans or discount < 0:
                raise self._refused(con, call_id, actor, Tool.QUOTE_RENEWAL,
                                    ApiError.invalid_option(ErrorCode.INVALID_OPTION))
            addons = loads(p["addons"], [])
            annual = int(p["renewal_premium"])
            for code in drop:
                addon = next((a for a in reversed(addons) if a.get("code") == code), None)
                if addon is None or not addon.get("optional") or not pb.removable_optional_addons:
                    raise self._refused(con, call_id, actor, Tool.QUOTE_RENEWAL,
                                        ApiError.invalid_option(ErrorCode.INVALID_OPTION))
                annual -= int(addon.get("premium") or 0)
            annual = int((Decimal(annual) * (100 - discount) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            instalments = 4 if plan == PaymentPlanInstalments.QUARTERLY else 1
            per = math.ceil(Decimal(annual) / instalments)
            quote_id = str(uuid.uuid4())
            stored = {"quoteId": quote_id, "annualPremium": annual, "instalments": instalments,
                      "perInstalment": per, "paymentPlan": plan, "dropAddons": drop, "discountPercent": discount}
            con.execute("UPDATE calls SET last_quote = ? WHERE id = ?", (dumps(stored), call_id))
            self.audit.record(con, call_id, actor, AuditAction.TOOL_QUOTE_RENEWAL,
                              {**stored, "turnIndex": _turn_count(c)})
            return {"quoteId": quote_id, "annualPremium": annual, "instalments": instalments, "perInstalment": per,
                    "mustHandoff": bool(c["must_handoff"])}

    def payment_link(self, call_id: str, quote_id: str | None, actor: str) -> dict:
        with self.db.tx() as con:
            c = self._offerable_call(con, call_id, Tool.SEND_PAYMENT_LINK, actor)
            last = loads(c["last_quote"])
            if not quote_id or last is None or str(quote_id) != last.get("quoteId"):
                raise self._refused(con, call_id, actor, Tool.SEND_PAYMENT_LINK,
                                    ApiError.conflict(ErrorCode.STALE_QUOTE))
            con.execute("UPDATE calls SET payment_link_sent = 1 WHERE id = ?", (call_id,))
            self.audit.record(con, call_id, actor, AuditAction.TOOL_SEND_PAYMENT_LINK,
                              {"quoteId": str(quote_id), "channel": DeliveryChannel.SMS,
                               "turnIndex": _turn_count(c)})
            return {"sent": True, "channel": DeliveryChannel.SMS, "mobileLast4": self._policy(con, c)["mobile_last4"],
                    "mustHandoff": bool(c["must_handoff"])}

    def handoff(self, call_id: str, reason: str | None, callback_at: str | None, actor: str) -> dict:
        with self.db.tx() as con:
            c = self._open_call(con, call_id, Tool.HANDOFF_TO_HUMAN, actor)
            if not reason or not reason.strip():
                raise ApiError.bad_request("reason is required")
            con.execute("UPDATE calls SET handoff_reason = ?, must_handoff = 1, callback_at = ? WHERE id = ?",
                        (reason, callback_at, call_id))
            self.audit.record(con, call_id, actor, AuditAction.TOOL_HANDOFF_TO_HUMAN,
                              {"reason": reason, "callbackAt": callback_at, "turnIndex": _turn_count(c)})
            self._set_case_status(con, call_id, CaseStatus.ESCALATED)
            return {"queued": True, "mustHandoff": True}

    def turn(self, call_id: str, role: str | None, text: str | None, at: str | None, actor: str) -> None:
        with self.db.tx() as con:
            c = self._open_call(con, call_id, Tool.TURN, actor)
            if role not in (TurnRole.AGENT, TurnRole.CUSTOMER):
                raise ApiError.bad_request("role must be agent or customer")
            if text is None or not text.strip():
                raise ApiError.bad_request("text is required")
            transcript = loads(c["transcript"], [])
            transcript.append({"role": role, "text": text, "at": at})
            con.execute("UPDATE calls SET transcript = ? WHERE id = ?", (dumps(transcript), call_id))

    def end(self, call_id: str, actor: str) -> dict:
        with self.db.tx() as con:
            c = self._find(con, call_id)
            if c["ended_at"] is not None:
                return {"outcome": c["outcome"], "mustHandoff": bool(c["must_handoff"])}
            if c["handoff_reason"] is not None:
                outcome = RenewalOutcome.HANDED_OFF
            elif c["payment_link_sent"]:
                outcome = RenewalOutcome.RENEWAL_PENDING_PAYMENT
            else:
                outcome = RenewalOutcome.NO_DECISION
            con.execute("UPDATE calls SET outcome = ?, ended_at = ? WHERE id = ?",
                        (outcome, self.clock.instant(), call_id))
            status = con.execute("SELECT status FROM cases WHERE id = ?", (call_id,)).fetchone()["status"]
            if status != CaseStatus.ESCALATED:
                self._set_case_status(con, call_id, CaseStatus.NEEDS_REVIEW)
            self.audit.record(con, call_id, actor, AuditAction.CALL_ENDED, {"outcome": outcome})
            return {"outcome": outcome, "mustHandoff": bool(c["must_handoff"])}

    # ---- guards ----

    def _find(self, con: sqlite3.Connection, call_id: str) -> sqlite3.Row:
        c = con.execute("SELECT * FROM calls WHERE id = ? AND kind = ?", (call_id, CallKind.RENEWAL)).fetchone()
        if c is None:
            raise ApiError.not_found(f"Call {call_id} not found")
        return c

    def _refused(self, con: sqlite3.Connection, call_id: str, actor: str, tool: Tool, e: ApiError) -> ApiError:
        self.audit.record(con, call_id, actor, AuditAction.TOOL_REFUSED, {"tool": tool, "code": e.detail})
        return e

    def _open_call(self, con, call_id: str, tool: Tool, actor: str) -> sqlite3.Row:
        c = self._find(con, call_id)
        if c["ended_at"] is not None:
            raise self._refused(con, call_id, actor, tool, ApiError.conflict(ErrorCode.CALL_ENDED))
        return c

    def _verified_call(self, con, call_id: str, tool: Tool, actor: str) -> sqlite3.Row:
        c = self._open_call(con, call_id, tool, actor)
        if not c["identity_verified"]:
            raise self._refused(con, call_id, actor, tool, ApiError.forbidden(ErrorCode.IDENTITY_NOT_VERIFIED))
        return c

    def _offerable_call(self, con, call_id: str, tool: Tool, actor: str) -> sqlite3.Row:
        c = self._verified_call(con, call_id, tool, actor)
        if c["must_handoff"]:
            raise self._refused(con, call_id, actor, tool, ApiError.conflict(ErrorCode.MUST_HANDOFF))
        return c

    def _policy(self, con, c: sqlite3.Row) -> sqlite3.Row:
        p = con.execute("SELECT * FROM policies WHERE id = ?", (c["policy_id"],)).fetchone()
        if p is None:
            raise ApiError.not_found(f"Policy {c['policy_id']} not found")
        return p

    def _set_case_status(self, con, case_id: str, status: CaseStatus) -> None:
        con.execute("UPDATE cases SET status = ?, updated_at = ? WHERE id = ?", (status, self.clock.instant(), case_id))

    def _greeting(self, p: sqlite3.Row) -> str:
        return self.playbook.greeting.replace("{holderName}", p["holder_name"])


def _parse_dob(raw: str | None) -> date:
    if raw is None or not DOB_PATTERN.match(raw):
        raise ApiError.bad_request("dateOfBirth must be YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError as e:
        raise ApiError.bad_request("dateOfBirth must be YYYY-MM-DD") from e


def _turn_count(c: sqlite3.Row) -> int:
    return len(loads(c["transcript"], []))


def _last_customer_turn(transcript: list, up_to: int) -> str | None:
    for i in range(min(up_to, len(transcript)) - 1, -1, -1):
        if transcript[i].get("role") == TurnRole.CUSTOMER:
            return transcript[i].get("text")
    return None
