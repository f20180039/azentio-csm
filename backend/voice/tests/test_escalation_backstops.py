"""Level 2 escalation backstops: a verification lock and repeated misunderstanding each hand the caller to a person,
once, through the same tool path as the model's own escalations; a failed hand-over is never spoken as done."""
import asyncio
import json

import httpx

from app.config import Settings
from app.simulator_client import SimulatorClient
from app.support_brain import UNCLEAR_BEFORE_ESCALATION, SupportBrain, op_outcome
from app.support_tools import CallSession
from tests.test_brain import Scripted, text, tool_call
from tests.test_support_brain import CALL, Found, make
from tests.test_support_tools import FakeSimulator

WRONG_DOB = {"mobile": "9876500002", "date_of_birth": "1990-01-01"}


def escalations(sim) -> list[dict]:
    return [json.loads(r.content) for r in sim.requests if r.url.path == "/v1/csm/escalations"]


def classifier(*per_turn: list[str]):
    """Returns the scripted intents for each customer turn, in order; no-speech turns never reach it."""
    queue = list(per_turn)

    async def classify(t, history):
        return Found(queue.pop(0), "rules")
    return classify


def test_lock_escalates_once():
    llm = Scripted(tool_call("verify_customer", WRONG_DOB, "c1"), text("That did not match. Shall we try again?"),
                   tool_call("verify_customer", WRONG_DOB, "c2"), text("Still no match. One more try?"),
                   tool_call("verify_customer", WRONG_DOB, "c3"), text("Verification is now locked."),
                   text("I can't verify you today, so a colleague will call you back; your reference is E S C seven zero two zero zero."),
                   tool_call("verify_customer", WRONG_DOB, "c4"), text("Verification stays locked; a colleague will be in touch."))
    brain, sim, _ = make(llm)
    turns = [asyncio.run(brain.reply("98765 00002, first January 1990")) for _ in range(3)]
    assert turns[2].locked and turns[2].verify_failures == 3
    raised = escalations(sim)
    assert len(raised) == 1 and raised[0]["category"] == "AUTH_LOCKED"
    assert raised[0]["summary"] == "Verification locked after 3 failed attempts"
    assert [t.name for t in turns[2].tool_calls] == ["verify_customer", "escalate_to_human"] and turns[2].refs == ["ESC-70200"]
    assert turns[2].text.startswith("I can't verify you today")  # the reply the caller hears follows the hand-over
    assert "ESC-70200" in json.dumps([m for m in llm.seen[-1] if m["role"] == "tool"])  # the model saw the reference
    fourth = asyncio.run(brain.reply("Try 98765 00002, first January 1990 again"))
    assert len(escalations(sim)) == 1 and fourth.refs == ["ESC-70200"]
    assert "Verification is now locked." not in [m.get("content") for m in brain._messages]  # the replaced reply left no trace


def test_a_caller_locked_on_an_earlier_call_is_escalated_without_a_count_that_did_not_happen():
    good = {"mobile": "9876500002", "date_of_birth": "1985-11-03"}
    llm = Scripted(tool_call("verify_customer", good), text("Verification is locked."),
                   text("I can't verify you today; a colleague will call you back, reference E S C seven zero two zero zero."))
    brain, sim, _ = make(llm)
    sim.failures = 3  # the bank locked this caller on an earlier call: the first attempt here comes back LOCKED
    turn = asyncio.run(brain.reply("98765 00002, third November 85"))
    assert turn.locked and turn.verify_failures == 0
    raised = escalations(sim)
    assert len(raised) == 1 and raised[0]["category"] == "AUTH_LOCKED"
    assert "0 failed attempts" not in raised[0]["summary"] and "failed attempts" not in raised[0]["summary"]
    assert raised[0]["summary"] == "Customer verification is locked; no attempt could be accepted on this call"
    assert turn.refs == ["ESC-70200"] and "seven zero two zero zero" in turn.text


def test_no_second_hand_over_when_the_model_already_tried_this_turn():
    class EscalationsDown(FakeSimulator):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/csm/escalations":
                self.requests.append(request)
                return httpx.Response(503, json={"error": "UNAVAILABLE"})
            return super().__call__(request)

    sim = EscalationsDown()
    llm = Scripted(text("Sorry?"), text("Pardon?"),
                   tool_call("escalate_to_human", {"trigger": "UNRESOLVED", "reason": "cannot follow", "summary": "unclear request"}),
                   text("I'm sorry, I can't reach a colleague right now."))
    brain = SupportBrain(llm, SimulatorClient(Settings(), transport=httpx.MockTransport(sim)), None, CallSession(CALL),
                         classifier(*[["UNCLEAR"]] * UNCLEAR_BEFORE_ESCALATION))
    turn = None
    for t in ("the thing", "that thing", "the thing again"):
        turn = asyncio.run(brain.reply(t))
    assert len(sim.requests) == 1 and [t.name for t in turn.tool_calls] == ["escalate_to_human"]  # the model's own attempt, no backstop
    assert "ESC-" not in turn.text and turn.refs == []


def test_three_unclear_turns_escalate_with_repeated_misunderstanding():
    llm = Scripted(text("Sorry, which product do you mean?"), text("Could you say that another way?"), text("I'm still not sure I follow."),
                   text("I'm sorry I couldn't follow; a colleague will call you back, reference E S C seven zero two zero zero."))
    brain, sim, _ = make(llm, classifier(*[["UNCLEAR"]] * UNCLEAR_BEFORE_ESCALATION))
    turns = [asyncio.run(brain.reply(t)) for t in ("the thing", "that thing from last time", "you know, the thing")]
    raised = escalations(sim)
    assert len(raised) == 1 and raised[0]["category"] == "REPEATED_MISUNDERSTANDING"
    assert turns[0].tool_calls == [] and turns[1].tool_calls == []
    assert [t.name for t in turns[2].tool_calls] == ["escalate_to_human"] and turns[2].refs == ["ESC-70200"]
    assert "ESC-70200" in json.dumps([m for m in llm.seen[-1] if m["role"] == "tool"])
    assert turns[2].text.startswith("I'm sorry I couldn't follow") and "seven zero two zero zero" in turns[2].text
    assert turns[2].intents == ["UNCLEAR"] and turns[2].verified is False


def test_misunderstanding_streak_ignores_no_speech_and_resets_on_understanding():
    llm = Scripted(*[text(f"Reply {n}.") for n in range(5)])
    brain, sim, _ = make(llm, classifier(["UNCLEAR"], ["UNCLEAR"], ["REPAYMENT"], ["UNCLEAR"], ["UNCLEAR"]))
    asyncio.run(brain.reply("the thing"))
    asyncio.run(brain.no_speech("silence"))
    assert brain.call.unclear_streak == 1
    asyncio.run(brain.reply("that thing"))
    assert brain.call.unclear_streak == 2
    asyncio.run(brain.reply("when is my EMI due"))
    assert brain.call.unclear_streak == 0
    asyncio.run(brain.reply("the thing"))
    asyncio.run(brain.reply("that thing"))
    assert brain.call.unclear_streak == 2 and escalations(sim) == [] and brain.call.refs == []


def test_backstop_escalation_failure_is_not_claimed():
    class EscalationsDown(FakeSimulator):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/csm/escalations":
                self.requests.append(request)
                return httpx.Response(503, json={"error": "UNAVAILABLE"})
            return super().__call__(request)

    sim = EscalationsDown()
    llm = Scripted(text("Sorry?"), text("Pardon?"), text("I'm not following."),
                   text("I'm sorry, I can't reach a colleague right now. Please call the helpline."))
    brain = SupportBrain(llm, SimulatorClient(Settings(), transport=httpx.MockTransport(sim)), None, CallSession(CALL),
                         classifier(*[["UNCLEAR"]] * UNCLEAR_BEFORE_ESCALATION))
    turn = None
    for t in ("the thing", "that thing", "the thing again"):
        turn = asyncio.run(brain.reply(t))
    assert len(sim.requests) == 1 and "ESC-" not in turn.text and turn.refs == [] and brain.call.refs == []
    trace = turn.tool_calls[0]
    assert trace.name == "escalate_to_human" and "error" in trace.result and op_outcome(trace.result) == "FAILED"
    assert "ESC-" not in json.dumps(llm.seen[-1])  # the model never saw a reference it could read out
    assert brain.call.unclear_streak == 0  # one attempt per run of misunderstandings, not a retry on every later unclear turn
