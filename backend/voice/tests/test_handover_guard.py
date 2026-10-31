"""A missing or misheard verification detail is never a reason to hand the caller to a person (call 475b0ac5, turn 7):
the agent asks again and reads back what it heard. Fraud, distress and a verification lock still hand over as before."""
import asyncio

import pytest

from app.support_tools import CallSession, is_fraud_handover, run_support_tool
from app.vocab import EscalationTrigger, RefPrefix, ToolError
from tests.test_brain import Scripted, text, tool_call
from tests.test_escalation_backstops import escalations
from tests.test_support_brain import CALL, make
from tests.test_support_tools import setup

NINE_DIGITS = {"mobile": "987650006", "date_of_birth": "1995-12-05"}
UNABLE_TO_VERIFY = {"trigger": EscalationTrigger.SENSITIVE, "reason": "Unable to verify caller",
                    "summary": "Caller could not provide 10-digit mobile number"}
NO_HANDOVER_NOTE = "Don't hand over for missing or misheard details. Ask again for what is missing, reading back what you heard."


def escalate(client, call, trigger, reason, summary=None):
    return asyncio.run(run_support_tool(client, call, "escalate_to_human", {"trigger": trigger, "reason": reason, "summary": summary or reason}))


def test_no_handover_for_missing_details():
    llm = Scripted(tool_call("verify_customer", NINE_DIGITS), text("I heard only 9 digits, 98765 0006; could you say the full number again?"),
                   tool_call("escalate_to_human", UNABLE_TO_VERIFY, "c2"), text("Sorry, I heard 98765 0006, nine digits. Once more, slowly?"))
    brain, sim, _ = make(llm)
    first = asyncio.run(brain.reply("987650006. Date of birth 1995-1205."))
    assert first.tool_calls[0].result["error"] == ToolError.MISSING_DETAILS
    second = asyncio.run(brain.reply("I already gave you the..."))
    refused = next(t.result for t in second.tool_calls if t.name == "escalate_to_human")
    assert refused == {"error": ToolError.ASK_FIRST, "note": NO_HANDOVER_NOTE}
    assert escalations(sim) == [] and second.refs == [] and brain.call.refs == []
    assert "ESC-" not in second.text and not brain.call.verified and not brain.call.locked


@pytest.mark.parametrize("trigger", [EscalationTrigger.SENSITIVE, EscalationTrigger.UNRESOLVED])
@pytest.mark.parametrize("reason", ["Unable to verify caller", "Caller could not provide 10-digit mobile number",
                                    "Could not confirm the caller's identity", "The date of birth was not heard clearly",
                                    "Caller did not give the details needed"])
def test_verification_reasons_are_refused_while_unverified(trigger, reason):
    sim, client, call = setup()
    out = escalate(client, call, trigger, reason)
    assert out["error"] == ToolError.ASK_FIRST and out["note"] == NO_HANDOVER_NOTE
    assert not [r for r in sim.requests if r.url.path.endswith("/escalations")] and call.refs == []


@pytest.mark.parametrize("reason", ["card payment I did not make", "The caller reports a transaction they did not authorise",
                                    "unauthorised debit while identity unconfirmed", "fraud on the account", "lost card, cannot verify yet",
                                    "card stolen, could not verify the caller"])
def test_fraud_handover_still_goes_through_unverified(reason):
    sim, client, call = setup()
    out = escalate(client, call, EscalationTrigger.SENSITIVE, reason)
    assert out["ref"].startswith(RefPrefix.ESCALATION) and "error" not in out and call.refs == [out["ref"]]
    assert len([r for r in sim.requests if r.url.path.endswith("/escalations")]) == 1


def test_distress_and_dissatisfaction_still_hand_over_unverified():
    sim, client, call = setup()
    assert escalate(client, call, EscalationTrigger.SENSITIVE, "caller in distress and crying")["ref"].startswith(RefPrefix.ESCALATION)
    sim, client, call = setup()
    assert escalate(client, call, EscalationTrigger.DISSATISFIED, "frustrated by the repeated mobile number questions")["ref"].startswith(RefPrefix.ESCALATION)


def test_a_verified_caller_is_never_held_back():
    sim, client, call = setup()
    call.session = "tok"
    assert escalate(client, call, EscalationTrigger.SENSITIVE, "Unable to verify caller")["ref"].startswith(RefPrefix.ESCALATION)


def test_locked_caller_is_still_escalated():
    sim, client, call = setup()
    call.locked = True
    out = escalate(client, call, EscalationTrigger.AUTH_LOCKED, "The caller could not be verified and verification is locked",
                   "Verification locked after 3 failed attempts")
    assert out["ref"].startswith(RefPrefix.ESCALATION) and call.refs == [out["ref"]]
    sim, client, call = setup()
    call.locked = True  # even a model-chosen trigger with a verification reason goes through once the bank has locked the caller
    assert escalate(client, call, EscalationTrigger.SENSITIVE, "Unable to verify caller")["ref"].startswith(RefPrefix.ESCALATION)


def test_lock_backstop_still_hands_over_through_the_brain():
    wrong = {"mobile": "9876500002", "date_of_birth": "1990-01-01"}
    llm = Scripted(tool_call("verify_customer", wrong, "c1"), text("No match; again?"), tool_call("verify_customer", wrong, "c2"), text("Still no; again?"),
                   tool_call("verify_customer", wrong, "c3"), text("Locked."), text("A colleague will call you back, reference ESC-70200."))
    brain, sim, _ = make(llm)
    turn = None
    for _ in range(3):
        turn = asyncio.run(brain.reply("98765 00002, first January 1990"))
    raised = escalations(sim)
    assert turn.locked and len(raised) == 1 and raised[0]["category"] == EscalationTrigger.AUTH_LOCKED and turn.refs == ["ESC-70200"]


def test_is_fraud_handover():
    assert is_fraud_handover("a payment I never made") and is_fraud_handover("stolen card") and is_fraud_handover("Fraudulent UPI debit")
    assert not is_fraud_handover("Unable to verify caller") and not is_fraud_handover("")
