"""Hindi callers (H1): script detection, call-language tracking, Hindi voice, fixed lines, greeting, prompts, classifier;
(H2) the eval renderer, harness accent and scenarios 15-16."""
import asyncio

from app import support_pipeline
from app.config import Settings
from app.intents import SYSTEM_PROMPT
from app.speech import (BILINGUAL_PROMPT, CODE_MIX_SHARE, HINDI_PROMPT, KANNADA_PROMPT, KANNADA_VOICE, VOICES, CallLanguage,
                        is_mostly_hindi, is_mostly_kannada, normalise_refs, script_language, voice_for)
from app.support_pipeline import HINDI_LINES, KANNADA_LINES, LINES, STILL_THERE
from app.support_prompt import GREETING, GREETING_HINDI, GREETING_KANNADA, LANGUAGE_RULE, language_rule, support_prompt
from app.vocab import SpeechLanguage
from eval.audio.render import VOICES as RENDER_VOICES
from eval.audio.render import manifest_rows
from eval.run_scenarios import ACCENTS, ENGLISH_ACCENTS, load
from tests.test_pause import FakeBrain, responder, run

EN, KN, HI = SpeechLanguage.ENGLISH, SpeechLanguage.KANNADA, SpeechLanguage.HINDI
ALL = (EN, KN, HI)
DEFAULT_VOICE = "en-IN-NeerjaNeural"
HINDI_VOICE = "hi-IN-SwaraNeural"
# The en,kn LANGUAGE rule exactly as it was before Hindi (C8): language_rule() must keep reproducing it
PRE_HINDI_LANGUAGE_RULE = (
    "reply in the language the caller used: English, or Kannada in Kannada script (mixed Kannada-English is fine, "
    "e.g. EMI, loan, statement in English). In Kannada too, say amounts as digits with the rupee sign (₹12,450) or "
    "the *_spoken form, and read references letter by letter. Kannada callers may say their mobile number and date of birth in Kannada number "
    "words (ಸೊನ್ನೆ 0, ಒಂದು 1, ಎರಡು 2, ಮೂರು 3, ನಾಲ್ಕು 4, ಐದು 5, ಆರು 6, ಏಳು 7, ಎಂಟು 8, ಒಂಬತ್ತು 9); convert them to digits yourself. Every line quoted in these instructions (the rating question, the reference read-back, "
    "the goodbye) is said in the caller's language. Tool calls and their arguments are always in English.")


def test_hindi_is_a_speech_language_with_its_own_voice():
    assert SpeechLanguage("hi") is HI
    assert VOICES == {KN: "kn-IN-SapnaNeural", HI: HINDI_VOICE} and KANNADA_VOICE == VOICES[KN]
    assert CODE_MIX_SHARE == 0.3


def test_script_language_reads_the_script():
    assert script_language("मेरी अगली EMI कब है") == HI
    assert script_language("ನನ್ನ ಸಾಲದ ಕಂತು") == KN
    assert script_language("when is my EMI") == EN
    assert script_language("میری EMI کب ہے") == EN  # letters, but neither script
    for no_letters in ("", None, "98765 00002", "₹12,450"):
        assert script_language(no_letters) is None


def test_hindi_call_switches_and_back():
    lang = CallLanguage(ALL)
    assert lang.current == EN
    lang.heard("मेरी अगली EMI कब है")
    assert lang.current == HI
    lang.heard("when is my EMI")
    assert lang.current == EN
    lang.heard("ನನ್ನ ಸಾಲದ ಕಂತು")
    assert lang.current == KN


def test_code_mixed_hindi_switches_the_call():
    lang = CallLanguage(ALL)
    lang.heard("मेरा loan statement चाहिए")
    assert lang.current == HI


def test_romanised_or_urdu_hindi_keeps_the_call_english():
    for text in ("meri EMI kab hai", "میری EMI کب ہے"):
        lang = CallLanguage(ALL)
        lang.heard(text)
        assert lang.current == EN, text


def test_hindi_not_enabled_stays_english():
    lang = CallLanguage((EN, KN))
    lang.heard("मेरी अगली EMI कब है")
    assert lang.current == EN


def test_hindi_reply_gets_the_hindi_voice():
    assert voice_for("आपकी अगली EMI ₹12,450 है।", DEFAULT_VOICE) == HINDI_VOICE
    assert voice_for("Your next EMI is 12,450 rupees.", DEFAULT_VOICE) == DEFAULT_VOICE
    hindi_call = CallLanguage(ALL)
    hindi_call.heard("मेरी अगली EMI कब है")
    assert voice_for("Sorry, I didn't catch that.", DEFAULT_VOICE, hindi_call) == HINDI_VOICE
    assert voice_for("ನಿಮ್ಮ ಮುಂದಿನ EMI ₹12,450.", DEFAULT_VOICE, hindi_call) == KANNADA_VOICE  # the reply's script wins


def test_devanagari_digits_become_ascii():
    assert normalise_refs("मेरा नंबर ९८७६५००००२") == "मेरा नंबर 9876500002"
    assert normalise_refs("ನನ್ನ ನಂಬರ್ ೯೩೮೦೯೩೯೨೮೦") == "ನನ್ನ ನಂಬರ್ 9380939280"


def test_fixed_lines_follow_a_hindi_call():
    assert set(HINDI_LINES) == set(KANNADA_LINES) and LINES == {KN: KANNADA_LINES, HI: HINDI_LINES}
    assert all(is_mostly_hindi(v) for v in HINDI_LINES.values())
    assert not any(is_mostly_kannada(v) for v in HINDI_LINES.values())
    assert is_mostly_hindi(GREETING_HINDI)
    language = CallLanguage(ALL)
    r, _ = responder(language=language)
    assert r.line(STILL_THERE) == STILL_THERE
    language.heard("मेरी अगली EMI कब है")
    assert r.line(STILL_THERE) == HINDI_LINES[STILL_THERE] == "क्या आप अभी भी लाइन पर हैं?"
    language.heard("ನನ್ನ ಸಾಲದ ಕಂತು")
    assert r.line(STILL_THERE) == KANNADA_LINES[STILL_THERE]


CALL_ID = FakeBrain().call.call_id


def test_greeting_offers_each_enabled_language():
    from tests.test_pipeline import FakeTransport

    for languages, expected in ((ALL, [GREETING, GREETING_KANNADA, GREETING_HINDI]), ((EN, HI), [GREETING, GREETING_HINDI])):
        transport = FakeTransport()
        task = support_pipeline.build_support_pipeline(Settings(groq_api_key="test-key", voice_languages=languages), FakeBrain(), transport)
        queued = []

        async def record(frames, queued=queued):
            queued.extend(frames)
        task.queue_frames = record
        try:
            run(transport._call_event_handler("on_client_connected", None))
            assert [f.text for f in queued] == expected
        finally:
            support_pipeline.LIVE.pop(CALL_ID, None)


def test_stt_prompt_follows_the_call():
    lang = CallLanguage(ALL)
    assert "ಬ್ಯಾಂಕ್" in lang.stt_prompt() and "बैंक" in lang.stt_prompt() and lang.stt_prompt().startswith("Bank customer call.")
    lang.heard("मेरी अगली EMI कब है")
    assert lang.stt_prompt() == HINDI_PROMPT == "बैंक ग्राहक कॉल। EMI, लोन, खाता, स्टेटमेंट, किस्त, NACH, KYC, SR-40102."
    lang.heard("ನನ್ನ ಸಾಲದ ಕಂತು")
    assert lang.stt_prompt() == KANNADA_PROMPT
    assert CallLanguage((EN, KN)).stt_prompt() == BILINGUAL_PROMPT
    en_hi = CallLanguage((EN, HI)).stt_prompt()
    assert "बैंक" in en_hi and "ಬ್ಯಾಂಕ್" not in en_hi
    for prompt in (CallLanguage(ALL).stt_prompt(), en_hi):  # the English terms once, the Hindi header with its own danda
        assert prompt.count("EMI") == 1 and "।" in prompt and "कॉल." not in prompt, prompt
    assert CallLanguage((HI,)).stt_prompt() == HINDI_PROMPT and CallLanguage((HI,)).stt_language() == "hi"


def test_prompt_language_rule_names_only_enabled_languages():
    en_hi = language_rule((EN, HI))
    assert "Hindi in Devanagari script (Hindi-English mixing is fine)" in en_hi and "Kannada" not in en_hi
    assert "शून्य 0, एक 1, दो 2, तीन 3, चार 4, पाँच 5, छह 6, सात 7, आठ 8, नौ 9" in en_hi
    assert LANGUAGE_RULE == PRE_HINDI_LANGUAGE_RULE and language_rule((EN, KN)) == LANGUAGE_RULE and "Hindi" not in LANGUAGE_RULE
    assert language_rule((EN,)) == "reply in English."
    all_three = language_rule(ALL)
    assert "Kannada" in all_three and "Hindi" in all_three and "always in English" in all_three
    assert en_hi in support_prompt(languages=(EN, HI)) and "Hindi" not in support_prompt()


def test_classifier_knows_hindi():
    assert "मेरी अगली EMI कब है?" in SYSTEM_PROMPT and "मुझे लोन स्टेटमेंट चाहिए" in SYSTEM_PROMPT and "Hindi" in SYSTEM_PROMPT


def test_live_speech_to_text_prompt_follows_a_hindi_call():
    from types import SimpleNamespace

    from app.speech import build_stt
    from tests.test_kannada import FakeTranscriptions

    stt = build_stt(Settings(groq_api_key="k", voice_languages=ALL))
    fake = FakeTranscriptions("मुझे लोन स्टेटमेंट चाहिए")
    stt._client = SimpleNamespace(audio=SimpleNamespace(transcriptions=fake))

    async def hear():
        return [f async for f in stt.run_stt(b"wav")]
    asyncio.run(hear())
    asyncio.run(hear())
    first, second = fake.calls
    assert "language" not in first and "बैंक" in first["prompt"] and "ಬ್ಯಾಂಕ್" in first["prompt"]
    assert second["prompt"] == HINDI_PROMPT and stt.call_language.current == HI


def test_renderer_and_harness_accept_hindi(tmp_path):
    assert RENDER_VOICES["hi"] == "hi-IN-MadhurNeural"  # the caller's voice; the agent replies with hi-IN-SwaraNeural
    assert "hi" in ACCENTS and "hi" not in ENGLISH_ACCENTS  # --full stays on the English accents
    rows = manifest_rows([{"id": "15-hindi-repayment", "turn": 1, "text": "मेरी अगली EMI कब है?", "intents": ["REPAYMENT"]}],
                         "scenarios", ["hi"], ["clean"], tmp_path)
    assert rows[0]["file"] == "scenarios/hi/clean/15-hindi-repayment_t01.wav"
    scenarios = {s["id"]: s for s in load()}
    for sid in ("15-hindi-repayment", "16-hindi-statement"):
        sc = scenarios[sid]
        assert sc["customer"] == {"mobile": "9876500002", "dob": "1985-11-03"}
        assert all(is_mostly_hindi(t["say"]) for t in sc["turns"])
        assert sc["turns"][1]["expect"] == {"intents": ["IDENTITY"], "verified": True}
    assert scenarios["15-hindi-repayment"]["turns"][-1]["expect"]["tools_any"] == ["get_loans", "get_schedule"]
    assert scenarios["16-hindi-statement"]["turns"][-1]["expect"]["creates"] == {"ticket": "STATEMENT"}
