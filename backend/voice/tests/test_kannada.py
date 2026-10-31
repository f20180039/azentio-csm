"""Kannada callers (C8): language setting, call-language tracking, Kannada voice, prompt rules, classifier, eval inputs."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import edge_tts_service, main, speech, speech_file
from app.config import Settings, load_settings, parse_languages
from app.intents import SYSTEM_PROMPT, Intent, classify, rules_classify
from app.speech import (BILINGUAL_PROMPT, DOMAIN_PROMPT, KANNADA_PROMPT, KANNADA_VOICE, CallLanguage, build_stt,
                        is_invented_segment, is_mostly_kannada, voice_for)
from app.support_prompt import LANGUAGE_RULE, support_prompt
from app.vocab import SpeechLanguage
from eval.audio.render import VOICES, manifest_rows
from eval.run_scenarios import ACCENTS, ENGLISH_ACCENTS, load
from tests.test_sim_audio import SPEECH

EN, KN = SpeechLanguage.ENGLISH, SpeechLanguage.KANNADA
EN_KN = (EN, KN)
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "kannada_stt_segments.json").read_text(encoding="utf-8"))
# What Whisper wrote for the rendered Kannada turns (docs/stt-benchmark.md, "Kannada")
HEARD_KANNADA = ["ನನಮುಂದಿನ ಎಮೇಯಾವಾಗ.", "ನನವ್ ಮುಂದಿನ AMIASಟು ಯಾವಾಗ ಕಟ್ಟಬೇಕು.", "ನನಗೆ ನನನ ಲೋನ್, ಸ್ಟೇಟ್ಮೆಟ್ ಬೇಕು."]


def test_voice_languages_setting(tmp_path, monkeypatch):
    assert parse_languages("en,kn") == EN_KN and parse_languages(" KN , en, kn") == (KN, EN)
    assert parse_languages("") == (EN,) and Settings().voice_languages == (EN,)
    with pytest.raises(ValueError):
        parse_languages("en,xx")
    monkeypatch.setenv("VOICE_LANGUAGES", "en,kn")
    assert load_settings(None).voice_languages == EN_KN
    monkeypatch.delenv("VOICE_LANGUAGES")
    assert load_settings(None).voice_languages == (EN,)


def test_english_only_stays_pinned_to_english_with_the_domain_prompt():
    lang = CallLanguage()
    assert (lang.detects, lang.stt_language(), lang.stt_prompt()) == (False, "en", DOMAIN_PROMPT)
    lang.heard("ನನ್ನ ಮುಂದಿನ EMI ಯಾವಾಗ?")
    assert lang.current == EN and lang.stt_prompt() == DOMAIN_PROMPT


def test_with_kannada_whisper_detects_and_the_call_follows_the_caller():
    lang = CallLanguage(EN_KN)
    assert (lang.detects, lang.stt_language(), lang.stt_prompt(), lang.current) == (True, None, BILINGUAL_PROMPT, EN)
    lang.heard(HEARD_KANNADA[0])
    assert lang.current == KN and lang.stt_prompt() == KANNADA_PROMPT
    for no_words in ("", None, "98765 00002"):
        lang.heard(no_words)
    assert lang.current == KN  # digits alone do not switch the call back
    lang.heard("Can you check the status of SR-40200?")
    assert lang.current == EN and lang.stt_prompt() == BILINGUAL_PROMPT


def test_kannada_only_is_pinned_to_kannada():
    lang = CallLanguage((KN,))
    assert (lang.stt_language(), lang.stt_prompt(), lang.current) == ("kn", KANNADA_PROMPT, KN)


def test_kannada_script_detection():
    for text in HEARD_KANNADA + ["ನಿಮ್ಮ ಮುಂದಿನ EMI ₹12,450, 5 ನವೆಂಬರ್ ರಂದು."]:
        assert is_mostly_kannada(text), text
    for text in ("When is my next EMI?", "DEVITTO, STATEMENT REQUEST, MARDI.", "12,450", "", None):
        assert not is_mostly_kannada(text), text


def test_kannada_reply_gets_the_kannada_voice():
    assert voice_for("ನಿಮ್ಮ ಮುಂದಿನ EMI ₹12,450.", "en-IN-NeerjaNeural") == KANNADA_VOICE
    assert voice_for("Your next EMI is 12,450 rupees.", "en-IN-NeerjaNeural") == "en-IN-NeerjaNeural"
    kannada_call = CallLanguage(EN_KN)
    kannada_call.heard(HEARD_KANNADA[2])
    assert voice_for("Sorry, I didn't catch that.", "en-IN-NeerjaNeural", kannada_call) == KANNADA_VOICE


class FakeCommunicate:
    voices: list[str] = []

    def __init__(self, text, voice):
        FakeCommunicate.voices.append(voice)

    async def stream(self):
        return
        yield  # an async generator with no audio


def test_live_voice_switches_per_reply(monkeypatch):
    monkeypatch.setattr(edge_tts_service.edge_tts, "Communicate", FakeCommunicate)
    FakeCommunicate.voices = []
    tts = edge_tts_service.EdgeTTSService(voice="en-IN-NeerjaNeural", call_language=CallLanguage(EN_KN))

    async def speak(text):
        return [f async for f in tts.run_tts(text, "ctx")]
    asyncio.run(speak("ನಿಮ್ಮ ಮುಂದಿನ EMI ₹12,450."))
    asyncio.run(speak("Your next EMI is 12,450 rupees."))
    assert FakeCommunicate.voices == [KANNADA_VOICE, "en-IN-NeerjaNeural"]


def test_recorded_audio_reply_uses_the_kannada_voice(monkeypatch):
    import edge_tts
    monkeypatch.setattr(edge_tts, "Communicate", FakeCommunicate)
    FakeCommunicate.voices = []
    asyncio.run(main.spoken_reply("ನಿಮ್ಮ ಮುಂದಿನ EMI ₹12,450."))
    asyncio.run(main.spoken_reply("Your next EMI is 12,450 rupees."))
    assert FakeCommunicate.voices == [KANNADA_VOICE, main.state.settings().tts_voice]


class FakeTranscriptions:
    def __init__(self, text):
        self.calls, self.text = [], text

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text, segments=[{"text": self.text, "no_speech_prob": 0.0, "avg_logprob": -0.3}])


def test_live_speech_to_text_detects_language_and_follows_the_call():
    stt = build_stt(Settings(groq_api_key="k", voice_languages=EN_KN))
    fake = FakeTranscriptions(HEARD_KANNADA[2])
    stt._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=fake))

    async def hear():
        return [f async for f in stt.run_stt(b"wav")]
    frames = asyncio.run(hear())
    assert frames[0].text == HEARD_KANNADA[2] and frames[0].audio_wav == b"wav"
    asyncio.run(hear())
    first, second = fake.calls
    assert "language" not in first and first["prompt"] == BILINGUAL_PROMPT and first["response_format"] == "verbose_json"
    assert second["prompt"] == KANNADA_PROMPT and stt.call_language.current == KN


def test_live_speech_to_text_english_only_is_unchanged():
    stt = build_stt(Settings(groq_api_key="k"))
    fake = FakeTranscriptions("When is my next EMI?")
    stt._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=fake))
    asyncio.run(stt._transcribe(b"wav"))
    assert fake.calls[0]["language"] == "en" and fake.calls[0]["prompt"] == DOMAIN_PROMPT


def test_recorded_audio_detects_language_and_carries_it_across_turns():
    seen = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r.content)
        return httpx.Response(200, json={"text": HEARD_KANNADA[2], "language": "Hindi",  # Groq misnamed Kannada clips
                                         "segments": [FIXTURE["kept"][3]]})
    lang = CallLanguage(EN_KN)
    for _ in range(2):
        out = asyncio.run(speech_file.transcribe_file(SPEECH, api_key="k", model="m", transport=httpx.MockTransport(handler),
                                                      call_language=lang))
        assert out.text == FIXTURE["kept"][3]["text"].strip()
    assert b'name="language"' not in seen[0] and BILINGUAL_PROMPT.encode() in seen[0]
    assert KANNADA_PROMPT.encode() in seen[1] and BILINGUAL_PROMPT.encode() not in seen[1] and lang.current == KN


def test_confidence_filter_keeps_measured_kannada_segments():
    assert FIXTURE["kept"] and all(is_mostly_kannada(s["text"]) or "STATEMENT" in s["text"] for s in FIXTURE["kept"])
    for seg in FIXTURE["kept"]:
        assert not is_invented_segment(seg), seg
    for seg in FIXTURE["rejected"]:  # garbled output when the language was pinned to kn on a code-mixed turn
        assert is_invented_segment(seg), seg


def test_support_prompt_has_the_language_rule_only_when_kannada_is_on():
    from app.vocab import SpeechLanguage
    prompt = support_prompt(languages=(SpeechLanguage.ENGLISH, SpeechLanguage.KANNADA))
    assert LANGUAGE_RULE in prompt and "English only" not in prompt
    assert "Kannada" not in support_prompt() and "reply in English" in support_prompt()
    assert "Kannada" in LANGUAGE_RULE and "*_spoken" in LANGUAGE_RULE and "always in English" in LANGUAGE_RULE


def test_classifier_knows_kannada():
    assert "Kannada" in SYSTEM_PROMPT
    for text in HEARD_KANNADA:
        assert rules_classify(text).intents == [Intent.UNCLEAR]  # the keyword fallback does not read Kannada, and does not crash
    sent = []

    def handler(r: httpx.Request) -> httpx.Response:
        sent.append(json.loads(r.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"intents": ["REPAYMENT"], "confidence": 0.9}'}}]})
    result = asyncio.run(classify(HEARD_KANNADA[0], [], api_key="k", model="m", transport=httpx.MockTransport(handler)))
    assert result.intents == [Intent.REPAYMENT] and HEARD_KANNADA[0] in sent[0]["messages"][1]["content"]


def test_renderer_and_harness_accept_kannada(tmp_path):
    assert VOICES["kn"] == KANNADA_VOICE
    assert "kn" in ACCENTS and "kn" not in ENGLISH_ACCENTS  # --full stays on the English accents
    rows = manifest_rows([{"id": "13-kannada-repayment", "turn": 1, "text": "ನನ್ನ ಮುಂದಿನ EMI ಯಾವಾಗ?", "intents": ["REPAYMENT"]}],
                         "scenarios", ["kn"], ["clean"], tmp_path)
    assert rows[0]["file"] == "scenarios/kn/clean/13-kannada-repayment_t01.wav"
    scenarios = {s["id"]: s for s in load()}
    for sid in ("13-kannada-repayment", "14-kannada-statement"):
        sc = scenarios[sid]
        assert sc["customer"] == {"mobile": "9876500002", "dob": "1985-11-03"}
        assert is_mostly_kannada(sc["turns"][0]["say"])
    assert scenarios["14-kannada-statement"]["turns"][-1]["expect"]["creates"] == {"ticket": "STATEMENT"}
