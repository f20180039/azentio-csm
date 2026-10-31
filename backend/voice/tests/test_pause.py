"""Demo pause: side talk while a live call is paused is never heard, answered or hung up on; Kannada calls get Kannada fixed lines."""
import asyncio

from fastapi.testclient import TestClient
from pipecat.frames.frames import InterruptionFrame, TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection

from app import main, support_pipeline
from app.config import Settings
from app.speech import CallLanguage, normalise_refs
from app.support_brain import SupportTurn
from app.support_pipeline import IDLE_GOODBYE, KANNADA_LINES, STILL_THERE, SupportResponder, TurnGate
from app.support_prompt import GREETING, GREETING_KANNADA
from app.support_tools import CallSession
from app.vocab import Route, SpeechLanguage

CALL = "66666666-6666-6666-6666-666666666666"
EN_KN = (SpeechLanguage.ENGLISH, SpeechLanguage.KANNADA)


class FakeBrain:
    def __init__(self, reply="Your EMI is due on the fifth."):
        self.call = CallSession(CALL)
        self.replies, self.unheard = [], 0
        self._reply = reply

    async def reply(self, text, **_):
        self.replies.append(text)
        return SupportTurn(self._reply)

    def mark_unheard(self):
        self.unheard += 1


def responder(brain=None, language=None):
    r = SupportResponder(brain or FakeBrain(), language=language)
    pushed = []

    async def push(frame, *_):
        pushed.append(frame)

    async def interrupt():
        pushed.append(InterruptionFrame())
    r.push_frame = push
    r.broadcast_interruption = interrupt
    r._gate = TurnGate(r._answer, settle=0.01)
    return r, pushed


def transcript(text):
    return TranscriptionFrame(text, "user", "2026-10-31T10:00:00Z")


async def say(r, text):
    for f in (VADUserStartedSpeakingFrame(), VADUserStoppedSpeakingFrame(), transcript(text)):
        await SupportResponder.process_frame(r, f, FrameDirection.DOWNSTREAM)


def run(coro):
    return asyncio.run(coro)


async def _no_super(self, frame, direction):
    pass


def test_side_talk_while_paused_is_not_heard_or_answered(monkeypatch):
    monkeypatch.setattr(support_pipeline.FrameProcessor, "process_frame", _no_super)

    async def scenario():
        brain = FakeBrain()
        r, pushed = responder(brain)
        await r.set_paused(True)
        await say(r, "so as you can see the agent verified the caller")
        await asyncio.sleep(0.05)
        return brain, pushed
    brain, pushed = run(scenario())
    assert brain.replies == []
    assert not any(isinstance(f, (TranscriptionFrame, VADUserStartedSpeakingFrame)) for f in pushed)


def test_resuming_listens_again(monkeypatch):
    monkeypatch.setattr(support_pipeline.FrameProcessor, "process_frame", _no_super)

    async def scenario():
        brain = FakeBrain()
        r, pushed = responder(brain)
        await r.set_paused(True)
        await r.set_paused(False)
        await say(r, "when is my EMI")
        await asyncio.sleep(0.05)
        r._idle.pause()
        return brain, pushed
    brain, pushed = run(scenario())
    assert brain.replies == ["when is my EMI"]
    assert any(getattr(f, "text", None) == "Your EMI is due on the fifth." for f in pushed)


def test_pausing_cuts_the_agent_off_and_drops_a_reply_in_flight(monkeypatch):
    monkeypatch.setattr(support_pipeline.FrameProcessor, "process_frame", _no_super)

    class SlowBrain(FakeBrain):
        async def reply(self, text, **_):
            await asyncio.sleep(0.05)  # still thinking when the presenter pauses
            return await super().reply(text)

    async def scenario():
        brain = SlowBrain()
        r, pushed = responder(brain)
        await say(r, "when is my EMI")
        await asyncio.sleep(0.02)
        await r.set_paused(True)
        await asyncio.sleep(0.08)
        return brain, pushed
    brain, pushed = run(scenario())
    assert isinstance(pushed[0], InterruptionFrame)
    assert not any(getattr(f, "text", None) == "Your EMI is due on the fifth." for f in pushed)
    assert brain.unheard == 1


def test_no_silence_check_in_or_hang_up_while_paused():
    async def scenario():
        r, pushed = responder()
        r._idle = support_pipeline.IdleWatch(r._check_in, r._hang_up, prompt_after=0.01, hangup_after=0.01)
        r._idle.agent_done()
        await r.set_paused(True)
        await asyncio.sleep(0.05)
        return pushed
    assert [getattr(f, "text", None) for f in run(scenario()) if hasattr(f, "text")] == []


def test_pause_route_toggles_a_live_call_and_404s_otherwise():
    r, _ = responder()
    support_pipeline.LIVE[CALL] = r
    try:
        c = TestClient(main.app)
        path = Route.SUPPORT_PAUSE.format(call_id=CALL)
        assert c.post(path, json={"paused": True}).json() == {"paused": True}
        assert r.paused is True
        assert c.post(path, json={"paused": False}).json() == {"paused": False}
        assert c.post(path, json={}).status_code == 422
        assert c.post(Route.SUPPORT_PAUSE.format(call_id="77777777-7777-7777-7777-777777777777"), json={"paused": True}).status_code == 404
        assert c.post(Route.SUPPORT_PAUSE.format(call_id="not-a-uuid"), json={"paused": True}).status_code == 422
    finally:
        support_pipeline.LIVE.pop(CALL, None)
        r._idle.pause()


def test_fixed_lines_follow_a_kannada_call():
    language = CallLanguage(EN_KN)
    r, _ = responder(language=language)
    assert r.line(STILL_THERE) == STILL_THERE
    language.heard("ನನ್ನ ಸಾಲದ ಕಂತು ಯಾವಾಗ")
    assert r.line(STILL_THERE) == KANNADA_LINES[STILL_THERE]
    assert r.line(IDLE_GOODBYE) == KANNADA_LINES[IDLE_GOODBYE]


def test_every_fixed_line_has_a_kannada_version_in_kannada_script():
    from app.speech import is_mostly_kannada
    assert all(is_mostly_kannada(v) for v in KANNADA_LINES.values())
    assert is_mostly_kannada(GREETING_KANNADA)


def test_kannada_numerals_become_digits():
    assert normalise_refs("ನನ್ನ ನಂಬರ್ ೯೩೮೦೯೩೯೨೮೦") == "ನನ್ನ ನಂಬರ್ 9380939280"


def test_greeting_offers_kannada_only_when_kannada_is_on():
    from tests.test_pipeline import FakeTransport

    for languages, expected in (((SpeechLanguage.ENGLISH,), [GREETING]), (EN_KN, [GREETING, GREETING_KANNADA])):
        transport = FakeTransport()
        task = support_pipeline.build_support_pipeline(Settings(groq_api_key="test-key", voice_languages=languages), FakeBrain(), transport)
        queued = []

        async def record(frames, queued=queued):
            queued.extend(frames)
        task.queue_frames = record
        run(transport._call_event_handler("on_client_connected", None))
        assert [f.text for f in queued] == expected
        support_pipeline.LIVE.pop(CALL, None)


def test_two_live_calls_are_independent_and_pausing_one_leaves_the_other_listening(monkeypatch):
    """Two browser tabs on the mic are two support calls: each has its own brain, pipeline and pause state."""
    from tests.test_pipeline import FakeTransport

    monkeypatch.setattr(support_pipeline.FrameProcessor, "process_frame", _no_super)
    a, b = FakeBrain("Reply for tab A."), FakeBrain("Reply for tab B.")
    a.call, b.call = CallSession("11111111-1111-1111-1111-111111111111"), CallSession("22222222-2222-2222-2222-222222222222")
    settings = Settings(groq_api_key="test-key")
    for brain in (a, b):
        support_pipeline.build_support_pipeline(settings, brain, FakeTransport())
    try:
        ra, rb = support_pipeline.LIVE[a.call.call_id], support_pipeline.LIVE[b.call.call_id]
        assert ra is not rb

        async def scenario():
            for r in (ra, rb):
                r._gate = TurnGate(r._answer, settle=0.01)
                r.push_frame = lambda *_a, **_k: asyncio.sleep(0)
                r.broadcast_interruption = lambda: asyncio.sleep(0)
            await ra.set_paused(True)
            await say(ra, "side talk with the jury")
            await say(rb, "when is my EMI")
            await asyncio.sleep(0.05)
            for r in (ra, rb):
                r._idle.pause()
        run(scenario())
        assert a.replies == [] and b.replies == ["when is my EMI"]
    finally:
        support_pipeline.LIVE.pop(a.call.call_id, None)
        support_pipeline.LIVE.pop(b.call.call_id, None)
