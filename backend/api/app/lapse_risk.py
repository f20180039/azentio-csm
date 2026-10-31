"""Lapse-risk scoring and routing for the renewal queue (port of LapseRisk.java)."""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.vocab import SEVERITY_FACTOR, Route, Severity, SignalCode

REMINDER_BELOW = 0.35


@dataclass(frozen=True)
class Signal:
    code: SignalCode
    label: str
    severity: Severity
    weight: float

    def to_json(self) -> dict:
        return {"code": self.code, "label": self.label, "severity": self.severity, "weight": self.weight}


@dataclass(frozen=True)
class Risk:
    score: float
    signals: list[Signal]
    route: Route


def score(signals: list[Signal]) -> float:
    total = sum(s.weight * SEVERITY_FACTOR[s.severity] for s in signals)
    return float(Decimal(str(min(1.0, total))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def assess(p: dict, today: date) -> Risk:
    signals: list[Signal] = []
    days = (date.fromisoformat(p["expires_on"]) - today).days
    if 0 <= days <= 7:
        signals.append(Signal(SignalCode.EXPIRY_7D, "Expires within 7 days", Severity.HIGH, 0.40))
    elif 8 <= days <= 14:
        signals.append(Signal(SignalCode.EXPIRY_14D, "Expires within 14 days", Severity.MEDIUM, 0.40))
    renewal100 = int(p["renewal_premium"]) * 100
    last = int(p["last_premium"])
    if renewal100 >= last * 115:
        signals.append(Signal(SignalCode.PREMIUM_UP_15, "Premium up 15% or more", Severity.MEDIUM, 0.50))
    elif renewal100 >= last * 105:
        signals.append(Signal(SignalCode.PREMIUM_UP_5, "Premium up 5% to 15%", Severity.LOW, 0.50))
    if p.get("claim_rejected_12m"):
        signals.append(Signal(SignalCode.CLAIM_REJECTED, "Claim rejected in the last 12 months", Severity.HIGH, 0.30))
    if p.get("autodebit_failed"):
        signals.append(Signal(SignalCode.AUTODEBIT_FAILED, "Last auto-debit failed", Severity.MEDIUM, 0.40))
    if int(p.get("reminders_ignored") or 0) >= 2:
        signals.append(Signal(SignalCode.REMINDERS_IGNORED, "Ignored two or more reminders", Severity.LOW, 0.50))
    s = score(signals)
    if p.get("open_complaint") or p.get("do_not_call"):
        route = Route.HUMAN_ONLY
    elif s < REMINDER_BELOW:
        route = Route.REMINDER_SMS
    else:
        route = Route.AGENT_CALL
    return Risk(s, signals, route)
