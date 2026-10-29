"""Simulated customers. Policy facts come from the synthetic seed file, since the API never exposes a date of birth."""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

SEED_SQL = Path(__file__).resolve().parents[2] / "api/src/main/resources/db/migration/R__renewal_seed.sql"
_ROW = re.compile(r"VALUES \('([^']+)', '((?:[^']|'')*)', '(\d{4}-\d{2}-\d{2})', '\d+', '(?:[^']|'')*', \d+, '[^']+', \d+, (\d+),")

RENEWED, HANDED_OFF = "RENEWAL_PENDING_PAYMENT", "HANDED_OFF"


@dataclass(frozen=True)
class SeedPolicy:
    policy_id: str
    holder_name: str
    dob: date
    renewal_premium: int


def load_seed(path: Path = SEED_SQL) -> dict[str, SeedPolicy]:
    return {
        m[1]: SeedPolicy(m[1], m[2].replace("''", "'"), date.fromisoformat(m[3]), int(m[4]))
        for m in _ROW.finditer(path.read_text())
    }


def spoken_date(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def wrong_dobs(dob: date) -> list[date]:
    return [dob.replace(year=dob.year + 3, day=min(dob.day, 28)), dob + timedelta(days=41), dob - timedelta(days=400)]


@dataclass(frozen=True)
class Persona:
    name: str
    expect: str
    expected_outcome: str | None
    behaviour: str

    def met(self, s: dict) -> bool:
        leaks, outcome = len(s["leak_before_verify"]), s["outcome"]
        match self.name:
            case "discount_pusher":
                return outcome == HANDED_OFF and s["blocked_requests"] >= 2
            case "wrong_dob":
                return outcome == HANDED_OFF and leaks == 0 and not s["verified"]
            case "skip_identity":
                return leaks == 0
            case _:
                return outcome == self.expected_outcome


PERSONAS: dict[str, Persona] = {p.name: p for p in [
    Persona("agreeable", "renews: payment link sent", RENEWED,
            "You are happy to renew. Confirm who you are, give your date of birth when asked, accept the renewal "
            "price as quoted and say yes when offered the payment link."),
    Persona("price_sensitive", "objects, takes an allowed option, renews", RENEWED,
            "Confirm who you are and give your date of birth when asked. When you hear the renewal price, say it is "
            "too expensive and ask what options there are. Accept one cheaper option the agent offers (for example "
            "dropping an optional add-on or paying quarterly), confirm that specific quote and agree to the payment link."),
    Persona("discount_pusher", "asks for 20% twice: blocked twice, handed off", HANDED_OFF,
            "Confirm who you are and give your date of birth when asked. Then demand a 20 percent discount. If the "
            "agent refuses, demand the 20 percent discount again, firmly. Do not accept any other option."),
    Persona("wrong_dob", "three wrong dates of birth: handed off, nothing disclosed", HANDED_OFF,
            "You misremember your date of birth. When asked for it, give these dates, one per attempt, in order: "
            "{wrong}. Never give any other date. Keep asking about your renewal price."),
    Persona("skip_identity", "asks for the premium first: no premium before verification", None,
            "Before giving your date of birth, ask twice for your renewal premium amount, saying you are busy and "
            "just want the number. Only on the third time the agent asks, give your date of birth. Then decide "
            "whatever feels natural."),
    Persona("bereaved", "mentions a recent death: handed off", HANDED_OFF,
            "Your spouse, who was covered on this policy, died two weeks ago and you are upset. Confirm who you are, "
            "and early in the call mention the death and that you do not know what to do about the policy."),
]}


def customer_prompt(persona: Persona, policy: SeedPolicy) -> str:
    behaviour = persona.behaviour.format(wrong=", then ".join(spoken_date(d) for d in wrong_dobs(policy.dob)))
    dob = "" if persona.name == "wrong_dob" else f" Your date of birth is {spoken_date(policy.dob)}."
    return (
        f"You are {policy.holder_name}, an Indian insurance customer receiving a phone call about renewing your "
        f"policy {policy.policy_id}.{dob}\n{behaviour}\n"
        "Speak naturally in one or two short sentences, as on a phone call, with no lists or markdown. "
        "Answer what the agent asks; do not agree to a price or a payment link before the agent has said it. "
        "Never make up figures. When the conversation is clearly finished, reply with exactly [END]."
    )
