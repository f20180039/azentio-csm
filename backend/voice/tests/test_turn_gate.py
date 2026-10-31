import asyncio

from app.support_brain import SupportBrain
from app.support_pipeline import TurnGate
from app.support_tools import CallSession
from tests.test_brain import Scripted, text


def run(coro):
    return asyncio.run(coro)


def test_a_split_sentence_is_answered_once():
    async def scenario():
        answered = []

        async def answer(t, g):
            answered.append(t)
        gate = TurnGate(answer, settle=0.05)
        gate.user_started()
        gate.user_stopped()
        gate.transcript("I am looking for a...")  # voice detection split the sentence here
        gate.user_started()
        gate.user_stopped()
        gate.transcript("status of my loan.")
        await asyncio.sleep(0.15)
        return answered
    assert run(scenario()) == ["I am looking for a... status of my loan."]


def test_no_answer_while_the_caller_is_still_speaking():
    async def scenario():
        answered = []

        async def answer(t, g):
            answered.append(t)
        gate = TurnGate(answer, settle=0.05)
        gate.user_started()
        gate.transcript("my number is")  # a transcript can land while the caller has already resumed
        await asyncio.sleep(0.12)
        before = list(answered)
        gate.user_stopped()
        gate.transcript("98765 00002")
        await asyncio.sleep(0.12)
        return before, answered
    before, after = run(scenario())
    assert before == [] and after == ["my number is 98765 00002"]


def test_a_reply_prepared_before_the_caller_spoke_again_is_stale():
    async def scenario():
        seen = {}

        async def answer(t, g):
            seen["gen"] = g
            await asyncio.sleep(0.1)  # the language model is still thinking...
            seen["current"] = gate.is_current(g)
        gate = TurnGate(answer, settle=0.01)
        gate.transcript("when is my EMI")
        await asyncio.sleep(0.03)
        gate.user_started()  # ...when the caller starts talking again
        await asyncio.sleep(0.15)
        return seen
    assert run(scenario())["current"] is False


def test_unheard_reply_is_marked_in_context():
    brain = SupportBrain(Scripted(text("Your EMI is due on the fifth.")), None, None, CallSession("c"))
    run(brain.reply("when is my EMI"))
    brain.mark_unheard()
    assert brain._messages[-1]["content"].startswith("(Not heard: the caller interrupted")
