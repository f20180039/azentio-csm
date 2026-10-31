"""English on the record for Kannada and Hindi turns (T1): background translation patched onto the turn's meta, the reply
never waits for it, English turns are never sent, failures leave the turn alone; to_english over Groq via MockTransport."""
import asyncio
import json
import time

import httpx

from app import main
from app.api_client import SupportCallsApi
from app.config import Settings, load_settings
from app.simulator_client import SimulatorClient
from app.support_brain import TRANSLATE_GRACE_SECS, SupportBrain
from app.support_tools import CallSession
from app.translate import SYSTEM_PROMPT, to_english
from app.vocab import MetaKey, SpeechLanguage
from tests.test_brain import Scripted, text
from tests.test_support_tools import FakeSimulator

CALL = "77777777-7777-7777-7777-777777777777"
KANNADA_ASK = "ನನ್ನ ಮುಂದಿನ EMI ಯಾವಾಗ?"
KANNADA_REPLY = "ನಿಮ್ಮ ಮುಂದಿನ EMI ನವೆಂಬರ್ 5 ರಂದು ಬರುತ್ತದೆ."
HINDI_ASK = "मेरी अगली EMI कब है?"


def make(llm, translator):
    spring: list[tuple[str, str, dict | None]] = []

    def spring_handler(r: httpx.Request) -> httpx.Response:
        spring.append((r.method, r.url.path, json.loads(r.content) if r.content else None))
        return httpx.Response(200, json={})

    brain = SupportBrain(llm, SimulatorClient(Settings(), transport=httpx.MockTransport(FakeSimulator())),
                         SupportCallsApi(Settings(), transport=httpx.MockTransport(spring_handler)), CallSession(CALL),
                         translator=translator)
    return brain, spring


def patches(spring, key):
    return [(path.rsplit("/", 2)[1], body) for method, path, body in spring if method == "PATCH" and key in (body or {})]


def recorded(spring):
    return [body for method, path, body in spring if method == "POST" and path.endswith("/turns")]


def test_kannada_customer_and_agent_turns_get_english():
    asked = []

    async def translator(t: str):
        asked.append(t)
        return "When is my next EMI?" if t == KANNADA_ASK else "Your next EMI is due on 5 November."

    brain, spring = make(Scripted(text(KANNADA_REPLY)), translator)

    async def run():
        turn = await brain.reply(KANNADA_ASK)
        await brain.finish()
        return turn

    turn = asyncio.run(run())
    assert turn.text == KANNADA_REPLY  # the spoken reply is the original; English is for the record only
    assert asked == [KANNADA_ASK, KANNADA_REPLY]
    got = patches(spring, MetaKey.TEXT_EN)
    assert [body[MetaKey.TEXT_EN] for _, body in got] == ["When is my next EMI?", "Your next EMI is due on 5 November."]
    assert all(body[MetaKey.LANGUAGE] == "kn" for _, body in got)
    assert [seq for seq, _ in got] == ["1", "2"]  # customer turn, then the agent turn
    assert [t["text"] for t in recorded(spring)] == [KANNADA_ASK, KANNADA_REPLY]  # the record keeps the original words
    assert spring[-1][1].endswith("/end")  # finish waited for the translations before ending the call


def test_hindi_turn_is_recorded_as_hi():
    async def translator(t: str):
        return "When is my next EMI?"

    brain, spring = make(Scripted(text("Your next EMI is due on 5 November.")), translator)

    async def run():
        await brain.reply(HINDI_ASK)
        await brain.finish()

    asyncio.run(run())
    got = patches(spring, MetaKey.TEXT_EN)
    assert [(seq, body[MetaKey.LANGUAGE]) for seq, body in got] == [("1", "hi")]  # the English reply is not translated


def test_english_turns_are_not_translated():
    asked = []

    async def translator(t: str):
        asked.append(t)
        return "never"

    brain, spring = make(Scripted(text("Your EMI is due on the fifth.")), translator)

    async def run():
        await brain.reply("when is my EMI")
        await brain.finish()

    asyncio.run(run())
    assert asked == []
    assert patches(spring, MetaKey.TEXT_EN) == []
    assert not brain._pending


def test_no_translator_means_no_translation():
    brain, spring = make(Scripted(text(KANNADA_REPLY)), None)

    async def run():
        await brain.reply(KANNADA_ASK)
        await brain.finish()

    asyncio.run(run())
    assert patches(spring, MetaKey.TEXT_EN) == [] and not brain._pending


def test_translation_failure_leaves_the_turn_alone():
    async def gives_none(t: str):
        return None

    async def raises(t: str):
        raise RuntimeError("translator down")

    for translator in (gives_none, raises):
        brain, spring = make(Scripted(text(KANNADA_REPLY)), translator)

        async def run():
            turn = await brain.reply(KANNADA_ASK)
            await brain.finish()
            return turn

        turn = asyncio.run(run())
        assert turn.text == KANNADA_REPLY
        assert patches(spring, MetaKey.TEXT_EN) == [] and patches(spring, MetaKey.LANGUAGE) == []
        assert spring[-1][1].endswith("/end")


def test_reply_does_not_wait_for_translation():
    async def slow(t: str):
        await asyncio.sleep(0.5)
        return "When is my next EMI?"

    brain, spring = make(Scripted(text(KANNADA_REPLY)), slow)

    async def run():
        started = time.monotonic()
        await brain.reply(KANNADA_ASK)
        elapsed = time.monotonic() - started
        pending_after_reply = len(brain._pending)
        before_finish = patches(spring, MetaKey.TEXT_EN)
        await brain.finish()
        return elapsed, pending_after_reply, before_finish

    elapsed, pending_after_reply, before_finish = asyncio.run(run())
    assert elapsed < 0.3
    assert pending_after_reply == 2 and before_finish == []
    assert len(patches(spring, MetaKey.TEXT_EN)) == 2  # finish gave the translations their grace period


def test_finish_gives_up_after_the_grace_period(monkeypatch):
    monkeypatch.setattr("app.support_brain.TRANSLATE_GRACE_SECS", 0.1)

    async def never(t: str):
        await asyncio.sleep(5)
        return "late"

    brain, spring = make(Scripted(text(KANNADA_REPLY)), never)

    async def run():
        await brain.reply(KANNADA_ASK)
        started = time.monotonic()
        outcome = await brain.finish()
        for task in brain._pending:
            task.cancel()
        return outcome, time.monotonic() - started

    outcome, took = asyncio.run(run())
    assert outcome == "RESOLVED" and took < 1.0
    assert spring[-1][1].endswith("/end") and patches(spring, MetaKey.TEXT_EN) == []


def test_to_english_keeps_references_and_handles_errors():
    seen = []

    def groq(r: httpx.Request) -> httpx.Response:
        seen.append(json.loads(r.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Your request SR-40102 is in progress."}}]})

    out = asyncio.run(to_english("ನಿಮ್ಮ ವಿನಂತಿ SR-40102 ಪ್ರಗತಿಯಲ್ಲಿದೆ.", api_key="k", model="m", transport=httpx.MockTransport(groq)))
    assert out == "Your request SR-40102 is in progress."
    body = seen[0]
    assert body["model"] == "m" and body["temperature"] == 0
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert body["messages"][1]["content"] == "ನಿಮ್ಮ ವಿನಂತಿ SR-40102 ಪ್ರಗತಿಯಲ್ಲಿದೆ."
    assert "SR-40102, ₹12,450" in SYSTEM_PROMPT and "Output only the translation." in SYSTEM_PROMPT

    def down(r: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    assert asyncio.run(to_english("ನಮಸ್ಕಾರ", api_key="k", model="m", transport=httpx.MockTransport(down))) is None

    def empty(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    assert asyncio.run(to_english("ನಮಸ್ಕಾರ", api_key="k", model="m", transport=httpx.MockTransport(empty))) is None

    def broken(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    assert asyncio.run(to_english("ನಮಸ್ಕಾರ", api_key="k", model="m", transport=httpx.MockTransport(broken))) is None
    assert asyncio.run(to_english("ನಮಸ್ಕಾರ", api_key="", model="m", transport=httpx.MockTransport(groq))) is None  # keyless: no call
    assert len(seen) == 1


def test_translate_model_setting(monkeypatch):
    monkeypatch.delenv("VOICE_TRANSLATE_MODEL", raising=False)
    assert load_settings(None).translate_model == "openai/gpt-oss-20b"
    monkeypatch.setenv("VOICE_TRANSLATE_MODEL", "llama-3.3-70b-versatile")
    assert load_settings(None).translate_model == "llama-3.3-70b-versatile"


def test_state_translator_follows_the_groq_key():
    state = main.State()
    state._settings = Settings(groq_api_key="")
    assert state.translator() is None
    state._settings = Settings(groq_api_key="k", translate_model="m")
    assert callable(state.translator())
    assert TRANSLATE_GRACE_SECS == 3
    assert SpeechLanguage.KANNADA == "kn" and SpeechLanguage.HINDI == "hi"
