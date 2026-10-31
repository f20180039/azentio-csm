import asyncio
import io
import json
import wave
from pathlib import Path

import httpx
import numpy as np

from app import main, speech_file
from app.speech import is_invented_segment
from tests.test_brain import Scripted, text, tool_call
from tests.test_support_main import CALL, client

SPEECH = (Path(__file__).parent / "fixtures" / "emi_question.wav").read_bytes()  # synthetic voice: "When is my next EMI?"


def wav(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(samples.astype(np.int16).tobytes())
    return buf.getvalue()


SILENCE = wav(np.zeros(16000 * 2))
HISS = wav(np.random.default_rng(7).normal(0, 300, 16000 * 2))


def stt(text_out: str, segments=None):
    seen = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(200, json={"text": text_out, "segments": segments if segments is not None else
                                         [{"text": text_out, "no_speech_prob": 0.01, "avg_logprob": -0.2}]})
    return httpx.MockTransport(handler), seen


def test_speech_is_trimmed_and_compressed_before_upload():
    pcm, secs = speech_file.trimmed_speech(SPEECH)
    total = len(speech_file.decode_pcm16(SPEECH)) / 16000
    assert 0.8 < secs < total - 0.6  # the padded silence is gone, the words remain
    assert len(speech_file.encode_flac(pcm)) < len(SPEECH) / 2


def test_silence_and_hiss_never_reach_speech_to_text():
    transport, seen = stt("Thank you.")
    for audio in (SILENCE, HISS):
        out = asyncio.run(speech_file.transcribe_file(audio, api_key="k", model="m", transport=transport))
        assert out.text is None and out.upload_bytes == 0
    assert seen == []


def test_upload_carries_domain_prompt_language_and_flac():
    transport, seen = stt("When is my next EMI?")
    out = asyncio.run(speech_file.transcribe_file(SPEECH, api_key="k", model="whisper-large-v3", transport=transport))
    assert out.text == "When is my next EMI?"
    body = seen[0].content
    assert b'name="language"\r\n\r\nen' in body and b"EMI, NACH, KYC" in body and b"audio/flac" in body and b"verbose_json" in body


def test_invented_segments_are_dropped():
    assert is_invented_segment({"text": " Thank you.", "no_speech_prob": 0.1, "avg_logprob": -0.2})
    assert is_invented_segment({"text": "loan", "no_speech_prob": 0.9, "avg_logprob": -1.4})
    assert not is_invented_segment({"text": "When is my EMI", "no_speech_prob": 0.05, "avg_logprob": -0.3})
    transport, _ = stt("Thank you.", [{"text": "Thank you.", "no_speech_prob": 0.8, "avg_logprob": -1.2}])
    assert asyncio.run(speech_file.transcribe_file(SPEECH, api_key="k", model="m", transport=transport)).text is None


def test_sim_audio_runs_turns_in_order_and_marks_silence():
    llm = Scripted(tool_call("get_loans", {}), text("Sure. First, what's your registered mobile number?"))
    c, spring = client(llm)
    main.state.stt_transport, _ = stt("When is my next EMI?")
    resp = c.post("/sim/audio", files=[("files", ("t1.wav", SPEECH, "audio/wav")), ("files", ("t2.wav", SILENCE, "audio/wav"))],
                  data={"speak": "false"})
    body = resp.json()
    assert resp.status_code == 200 and body["call_id"] == CALL
    first, second = body["turns"]
    assert first["transcript"] == "When is my next EMI?" and first["tool_trace"][0]["result"]["error"] == "NOT_VERIFIED"
    assert first["tool_trace"][0]["outcome"] == "DECLINED"
    assert first["reply_text"].startswith("Sure.") and first["verified"] is False
    assert second["no_speech"] is True and second["reply_text"] is None
    recorded = [b for m, p, b in spring if m == "POST" and p.endswith("/turns")]
    assert [t["role"] for t in recorded] == ["agent", "customer", "agent", "customer"]  # greeting, turn 1, reply, silence
    assert recorded[-1]["meta"]["no_speech"] is True
    main.state.stt_transport = None


def test_sim_audio_rejects_bad_requests():
    c, _ = client(Scripted())
    assert c.post("/sim/audio", files=[("files", ("a.wav", SPEECH, "audio/wav"))], data={"call_id": "nope"}).status_code == 400
    assert c.post("/sim/audio", files=[("files", ("a.wav", SPEECH, "audio/wav"))], data={"call_id": CALL}).status_code == 404
    main.state.stt_transport, _ = stt("x")
    assert c.post("/sim/audio", files=[("files", ("a.txt", b"not audio", "text/plain"))]).status_code == 422
    main.state.stt_transport = None


def test_uploaded_turn_audio_is_kept_and_served(tmp_path, monkeypatch):
    from app import recordings
    monkeypatch.setattr(recordings, "RECORDINGS_DIR", tmp_path)
    llm = Scripted(text("Sure, what's your registered mobile number?"))
    c, spring = client(llm)
    main.state.stt_transport, _ = stt("When is my next EMI?")
    body = c.post("/sim/audio", files=[("files", ("t1.wav", SPEECH, "audio/wav"))], data={"speak": "false"}).json()
    patches = [b for m, p, b in spring if m == "PATCH"]
    assert patches and patches[-1].get("audio") is True
    seq = next(b for m, p, b in spring if m == "POST" and p.endswith("/turns") and b["role"] == "customer") and 2
    r = c.get(f"/support/calls/{body['call_id']}/turns/{seq}/audio")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == SPEECH
    assert c.get(f"/support/calls/{body['call_id']}/turns/99/audio").status_code == 404
    assert c.get("/support/calls/not-a-uuid/turns/1/audio").status_code == 404
    main.state.stt_transport = None


def test_live_segments_join_into_one_turn_recording():
    from app.recordings import join_wavs
    joined = join_wavs([SILENCE, SILENCE, b"not a wav"])
    with wave.open(io.BytesIO(joined)) as w:
        assert w.getframerate() == 16000 and w.getnframes() == 16000 * 4
    assert join_wavs([]) is None
