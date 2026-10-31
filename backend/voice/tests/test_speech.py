from pipecat.frames.frames import TranscriptionFrame

from app.config import Settings
from app.speech import (
    BILINGUAL_PROMPT,
    DOMAIN_PROMPT,
    MOBILE_EXAMPLE,
    MULTILINGUAL_PROMPT,
    build_stt,
    build_vad,
    is_invented_segment,
    is_phantom,
    keep_transcript,
    normalise_refs,
    normalise_spoken_digits,
)


def test_spoken_digit_multipliers_are_expanded():
    assert normalise_spoken_digits("98765 4 times 0 1") == "98765 0000 1"
    assert normalise_spoken_digits("four times zero") == "0000"
    assert normalise_spoken_digits("triple zero") == "000"
    assert normalise_spoken_digits("double 5") == "55"
    assert normalise_spoken_digits("4 zeroes") == "0000"
    assert normalise_spoken_digits("Yes, 98765-7700. 4 times 0, 1. 1990, April 12th is my date of birth.") == (
        "Yes, 98765-7700. 0000, 1. 1990, April 12th is my date of birth."
    )


def test_caller_digit_words_become_digits():
    # a run of three or more digit words is a number the caller spelled out (a mobile, a reference), stored as digits
    assert normalise_spoken_digits("my number is nine eight seven six five zero zero zero zero two") == "my number is 9876500002"
    # a pause inside a number ("five, oh oh…") no longer splits it when the two halves make one mobile (task R1; was "98765, 00002")
    assert normalise_spoken_digits("it is nine eight seven six five, oh oh oh oh two") == "it is 9876500002"
    assert normalise_spoken_digits("Nine Eight Seven six five double zero zero zero two") == "9876500002"
    # one or two digit words are ordinary words
    assert normalise_spoken_digits("I want one statement for two loans") == "I want one statement for two loans"
    assert normalise_spoken_digits("one two") == "one two"
    assert normalise_spoken_digits("double five") == "55"


def test_repeated_digits_survive_hyphens_and_oh():
    assert normalise_spoken_digits("nine eight seven six five double-zero double-zero two") == "9876500002"
    assert normalise_spoken_digits("nine eight seven six five double o double o two") == "9876500002"
    assert normalise_spoken_digits("triple-5") == "555"
    assert normalise_spoken_digits("double o") == "00"
    assert normalise_spoken_digits("triple oh") == "000"
    assert normalise_spoken_digits("oh, okay") == "oh, okay"  # 'oh' is a digit only inside a number or after a multiplier


def test_a_pause_inside_a_mobile_is_bridged_only_when_it_makes_one():
    assert normalise_spoken_digits("98765, 00002") == "9876500002"
    assert normalise_spoken_digits("98765. 00002") == "9876500002"
    assert normalise_spoken_digits("nine eight seven six five, four zeros, one") == "9876500001"
    assert normalise_spoken_digits("+91 98765, 00002") == "+919876500002"
    for text in ("I paid 500, 2 times", "SR-40102, 98765", "CMP-98765, 00002", "98765, 0002", "555, 555, 55"):
        assert normalise_spoken_digits(text) == text, text


def test_prompts_show_whisper_the_mobile_format():
    # unbenchmarked (docs/stt-benchmark.md): the example is there so repeated zeros come back as digits, not collapsed words
    assert MOBILE_EXAMPLE == "Mobile 98765 00001, date of birth 1985-11-03."
    for prompt in (DOMAIN_PROMPT, BILINGUAL_PROMPT, MULTILINGUAL_PROMPT):
        assert prompt.endswith(MOBILE_EXAMPLE) and prompt.count(MOBILE_EXAMPLE) == 1, prompt


def test_references_survive_accented_transcription():
    assert normalise_refs("What's the status of SR for 8213?") == "What's the status of SR-48213?"
    assert normalise_refs("status of S R four zero one zero two please") == "status of SR-40102 please"
    assert normalise_refs("my complaint CMP 50011") == "my complaint CMP-50011"
    assert normalise_refs("SR 40102 and also SR-40200") == "SR-40102 and also SR-40200"


def test_ordinary_numbers_and_words_are_left_alone():
    for text in ("I paid 5000 rupees", "for 2 years", "VL-31003 EMI", "I want to pay four thousand", "my sr is 40102"):
        assert normalise_refs(text) == text


def test_live_transcripts_are_filtered_then_normalised():
    assert keep_transcript(TranscriptionFrame("Thank you.", "u", "t")) is None
    assert keep_transcript(TranscriptionFrame("status of SR for 0102", "u", "t")) == "status of SR-40102"
    assert not is_phantom("okay") and not is_phantom("bye")  # callers say these


def test_logprob_carries_the_filter_on_turbo():
    assert is_invented_segment({"text": "loan please", "no_speech_prob": 0.0, "avg_logprob": -0.9})
    assert not is_invented_segment({"text": "When is my EMI", "no_speech_prob": 0.0, "avg_logprob": -0.36})


def test_live_services_use_the_benchmarked_settings():
    params = build_vad().params
    assert (params.confidence, params.min_volume, params.start_secs, params.stop_secs) == (0.7, 0.6, 0.3, 0.4)
    stt = build_stt(Settings(groq_api_key="k"))
    assert stt._settings.prompt == DOMAIN_PROMPT and str(stt._settings.language).endswith("en")


def test_live_transcripts_drop_segments_the_model_made_up_from_noise():
    from types import SimpleNamespace
    result = SimpleNamespace(segments=[
        SimpleNamespace(text=" When is my next EMI?", no_speech_prob=0.0, avg_logprob=-0.3),
        SimpleNamespace(text=" so the ok la mar vin", no_speech_prob=0.0, avg_logprob=-1.4),  # chatter from the room
    ])
    frame = TranscriptionFrame("When is my next EMI? so the ok la mar vin", "u", "t", result=result)
    assert keep_transcript(frame) == "When is my next EMI?"
    only_noise = TranscriptionFrame("so the ok", "u", "t", result=SimpleNamespace(segments=[
        SimpleNamespace(text="so the ok", no_speech_prob=0.7, avg_logprob=-1.1)]))
    assert keep_transcript(only_noise) is None


def test_live_speech_to_text_asks_for_confidence_scores():
    stt = build_stt(Settings(groq_api_key="k"))
    assert stt._include_prob_metrics is True
