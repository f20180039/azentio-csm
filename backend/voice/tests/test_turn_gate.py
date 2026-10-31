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


def test_silence_after_the_agent_checks_in_then_hangs_up():
    from app.support_pipeline import IdleWatch

    async def scenario():
        events = []

        async def prompt():
            events.append("still there?")

        async def hangup():
            events.append("hang up")
        idle = IdleWatch(prompt, hangup, prompt_after=0.05, hangup_after=0.03)
        idle.agent_done()                 # agent finished its reply
        await asyncio.sleep(0.08)
        idle.agent_done()                 # agent finished saying "are you still there?"
        await asyncio.sleep(0.06)
        return events
    assert run(scenario()) == ["still there?", "hang up"]


def test_caller_speech_resets_the_silence_check():
    from app.support_pipeline import IdleWatch

    async def scenario():
        events = []

        async def note(e):
            events.append(e)
        idle = IdleWatch(lambda: note("prompt"), lambda: note("hangup"), prompt_after=0.05, hangup_after=0.03)
        idle.agent_done()
        await asyncio.sleep(0.08)         # checked in once
        idle.caller_active()              # the caller answers
        idle.agent_done()                 # agent replies, then silence again
        await asyncio.sleep(0.03)
        return events, idle.prompted
    events, prompted = run(scenario())
    assert events == ["prompt"] and prompted is False  # no hang-up: the next silence starts with a fresh check-in


def test_live_call_timings_default_to_the_agreed_values():
    from app import support_pipeline as sp
    assert (sp.SETTLE_SECS, sp.IDLE_PROMPT_SECS, sp.IDLE_HANGUP_SECS) == (1.5, 5.0, 3.0)
