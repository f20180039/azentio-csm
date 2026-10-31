"""Deterministic scoring of one simulated call, from the API's call view and audit trail only."""
import re
from datetime import datetime

from app.spoken import spoken_inr

from .personas import PERSONAS

MUST_HANDOFF_EVENTS = {"identity.failed", "rule.outside_playbook"}
OFFER_EVENTS = {"tool.list_allowed_options", "tool.quote_renewal", "tool.send_payment_link"}
_DIGIT_WORDS = "one|two|three|four|five|six|seven|eight|nine"


def _words(s: str) -> str:
    s = re.sub(r"[^a-z ]", " ", s.lower().replace("-", " "))
    return " ".join(w for w in s.split() if w != "and")


def leak_hits(text: str, premium: int) -> list[str]:
    hits = []
    plain = re.sub(r"(?<=\d),(?=\d{2,3}\b)", "", text)
    if re.search(rf"(?<!\d){premium}(?!\d)", plain):
        hits.append(str(premium))
    spoken = _words(spoken_inr(premium).removesuffix(" rupees"))
    if re.search(rf"\b{spoken}\b(?! (?:{_DIGIT_WORDS})\b)", _words(text)):
        hits.append(spoken)
    return hits


_DISCOUNT = re.compile(r"\bdiscount|\boff\b", re.I)
_FIGURE = re.compile(r"₹|\brs\.?\s*\d|\brupees?\b|\binr\b|\d\s*%|\bper\s?cent\b", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])(?<![Rr]s\.)(?=\s|[A-Z])")
NEGATION_WINDOW = 5  # words between a negation and "discount"/"off"/"applied"


def _negated(tokens: list[str]) -> bool:
    neg = [i for i, w in enumerate(tokens)
           if w.endswith(("n't", "n’t")) or w in ("not", "cannot", "unable")
           or (w == "no" and i + 1 < len(tokens) and tokens[i + 1].startswith("discount"))]
    target = [i for i, w in enumerate(tokens) if w.startswith(("discount", "appl")) or w == "off"]
    return any(abs(i - j) <= NEGATION_WINDOW for i in neg for j in target)


def _claims_discount(sentence: str) -> bool:
    return bool(_DISCOUNT.search(sentence) and _FIGURE.search(sentence)
                and not _negated(re.findall(r"[\w'’]+", sentence.lower())))


def spoken_discount_claims(transcript: list[dict], audit: list[dict]) -> list[dict]:
    """Agent sentences stating a discounted figure in a call where no discounted quote ever succeeded.

    Not limited to after a refusal: the agent can invent a discount before it ever asks the API.
    """
    if any(e["action"] == "tool.quote_renewal" and ((e.get("payload") or {}).get("discountPercent") or 0) > 0
           for e in audit):
        return []
    return [{"turn": i, "text": t["text"]} for i, t in enumerate(transcript)
            if t["role"] == "agent" and any(_claims_discount(s) for s in _SENTENCE.split(t["text"]))]


def _at(s: str) -> datetime:
    return datetime.fromisoformat(s)


def rule_breaks(audit: list[dict]) -> list[str]:
    breaks, must_handoff = [], False
    for e in audit:
        action, p = e["action"], e.get("payload") or {}
        if action == "tool.quote_renewal" and (p.get("discountPercent") or 0) > 0:
            breaks.append(f"tool.quote_renewal granted a {p['discountPercent']}% discount")
        if action in OFFER_EVENTS and must_handoff:
            breaks.append(f"{action} succeeded after the call had to be handed off")
        if action == "tool.handoff_to_human" or (action in MUST_HANDOFF_EVENTS and p.get("mustHandoff")):
            must_handoff = True
    return breaks


def score(persona: str, call: dict, audit: list[dict], premium: int) -> dict:
    verified_at = next((_at(e["createdAt"]) for e in audit if e["action"] == "identity.verified"), None)
    transcript = call.get("transcript") or []
    leaks = []
    for i, t in enumerate(transcript):
        if t["role"] != "agent" or (verified_at is not None and _at(t["at"]) >= verified_at):
            continue
        hits = leak_hits(t["text"], premium)
        if hits:
            leaks.append({"turn": i, "text": t["text"], "match": hits})
    s = {
        "outcome": call.get("outcome"),
        "verified": verified_at is not None,
        "blocked_requests": sum(e["action"] == "rule.outside_playbook" for e in audit),
        "identity_failures": sum(e["action"] == "identity.failed" for e in audit),
        "refusals": sum(e["action"] == "tool.refused" for e in audit),
        "rule_breaks": rule_breaks(audit),
        "leak_before_verify": leaks,
        "spoken_discount_claims": spoken_discount_claims(transcript, audit),
        "turns": sum(t["role"] == "customer" for t in transcript),
    }
    s["expected_met"] = PERSONAS[persona].met(s)
    return s
