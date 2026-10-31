from pipecat.frames.frames import TranscriptionFrame

from app.config import Settings
from app.speech import DOMAIN_PROMPT, build_stt, build_vad, is_invented_segment, is_phantom, keep_transcript, normalise_refs


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
    assert (params.confidence, params.min_volume, params.start_secs, params.stop_secs) == (0.7, 0.6, 0.2, 0.4)
    stt = build_stt(Settings(groq_api_key="k"))
    assert stt._settings.prompt == DOMAIN_PROMPT and str(stt._settings.language).endswith("en")
