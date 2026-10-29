import asyncio

import httpx
import pytest
from pipecat.frames.frames import EndWorkerFrame, ErrorFrame, TTSSpeakFrame
from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregator
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.llm_service import LLMService
from pipecat.transports.base_transport import BaseTransport

from app.api_client import RenewalsApi
from app.config import Settings
from app import pipeline as pipeline_mod
from app.pipeline import GOODBYE, LLM_FALLBACK, build_pipeline
from app.prompt import system_prompt
from app.tools import TOOL_SCHEMAS

CALL = "22222222-2222-2222-2222-222222222222"
GREETING = "Hello, this is the Renewal Desk calling for Meera Iyer. Am I speaking with Meera Iyer?"


class FakeTransport(BaseTransport):
    def __init__(self):
        super().__init__()
        self._in, self._out = FrameProcessor(), FrameProcessor()
        self._register_event_handler("on_client_connected")
        self._register_event_handler("on_client_disconnected")

    def input(self):
        return self._in

    def output(self):
        return self._out


def api_with(handler) -> RenewalsApi:
    return RenewalsApi(Settings(), transport=httpx.MockTransport(handler))


def call_view(r: httpx.Request) -> httpx.Response:
    if r.method == "GET" and r.url.path.endswith(CALL):
        return httpx.Response(200, json={"greeting": GREETING, "holderName": "Meera Iyer"})
    return httpx.Response(200, json={"verified": True})


def flatten(processors):
    for p in processors:
        yield p
        yield from flatten(getattr(p, "processors", []) or [])


def build(handler=call_view):
    settings = Settings(groq_api_key="test-key")
    return asyncio.run(build_pipeline(settings, CALL, FakeTransport(), api=api_with(handler)))


def test_pipeline_params():
    task = build()
    procs = list(flatten(task.pipeline.processors))
    user = next(p for p in procs if isinstance(p, LLMUserAggregator))
    llm = next(p for p in procs if isinstance(p, LLMService))

    assert user._params.empty_user_turn is None
    assert user._params.vad_analyzer.params.stop_secs == 0.2
    assert user._params.user_turn_stop_timeout == 2.0
    assert set(llm._functions) == {t["function"]["name"] for t in TOOL_SCHEMAS}
    assert len(llm._functions) == 7
    assert user.context.get_messages()[0] == {"role": "assistant", "content": GREETING}
    assert llm._settings.system_instruction == system_prompt(GREETING)


def test_tool_handler_calls_the_api_and_returns_its_result():
    seen = []

    def handler(r):
        seen.append((r.method, r.url.path))
        return call_view(r)

    task = build(handler)
    llm = next(p for p in flatten(task.pipeline.processors) if isinstance(p, LLMService))
    results = []

    class Params:
        function_name = "verify_identity"
        arguments = {"date_of_birth": "1980-03-14"}

        @staticmethod
        async def result_callback(result, **_):
            results.append(result)

    asyncio.run(llm._functions["verify_identity"].handler(Params()))
    assert ("POST", f"/api/v1/renewals/calls/{CALL}/verify") in seen
    assert results == [{"verified": True}]


def test_unknown_call_is_rejected():
    with pytest.raises(LookupError):
        build(lambda r: httpx.Response(404, json={"detail": "NOT_FOUND"}))


def _llm(task):
    return next(p for p in flatten(task.pipeline.processors) if isinstance(p, LLMService))


def _params(name, results):
    class Params:
        function_name = name
        arguments = {}

        @staticmethod
        async def result_callback(result, properties=None):
            results.append((result, properties))

    return Params()


def test_end_call_speaks_goodbye_then_ends_the_pipeline():
    seen = []

    def handler(r):
        seen.append((r.method, r.url.path))
        return call_view(r)

    task = build(handler)
    llm = _llm(task)
    pushed, results = [], []

    async def record(frame, direction=None):
        pushed.append(frame)

    llm.push_frame = record
    asyncio.run(llm._functions["end_call"].handler(_params("end_call", results)))
    assert ("POST", f"/api/v1/renewals/calls/{CALL}/end") in seen
    assert results[0][1].run_llm is False
    assert isinstance(pushed[0], TTSSpeakFrame) and pushed[0].text == GOODBYE
    assert isinstance(pushed[1], EndWorkerFrame)
    assert len(pushed) == 2


def test_other_tools_do_not_end_the_pipeline():
    task = build()
    llm = _llm(task)
    pushed, results = [], []

    async def record(frame, direction=None):
        pushed.append(frame)

    llm.push_frame = record
    asyncio.run(llm._functions["get_policy"].handler(_params("get_policy", results)))
    assert pushed == []
    assert results[0][1] is None


def _error_handler(task):
    return task._event_handlers["on_pipeline_error"].handlers[-1]


def test_llm_error_speaks_a_fallback_at_most_once_per_ten_seconds(monkeypatch):
    task = build()
    llm = _llm(task)
    queued = []

    async def record(frames):
        queued.extend(frames)

    task.queue_frames = record
    clock = [1000.0]
    monkeypatch.setattr(pipeline_mod.time, "monotonic", lambda: clock[0])
    on_error = _error_handler(task)

    def fire():
        err = ErrorFrame(error="429 Too Many Requests")
        err.processor = llm
        asyncio.run(on_error(task, err))

    fire()
    assert [f.text for f in queued] == [LLM_FALLBACK]
    assert queued[0].append_to_context is False
    clock[0] += 9.9
    fire()
    assert len(queued) == 1
    clock[0] += 0.2
    fire()
    assert len(queued) == 2


def test_errors_from_other_processors_stay_silent():
    task = build()
    queued = []

    async def record(frames):
        queued.extend(frames)

    task.queue_frames = record
    err = ErrorFrame(error="stt down")
    err.processor = object()
    asyncio.run(_error_handler(task)(task, err))
    assert queued == []
