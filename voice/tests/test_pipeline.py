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
from app.llm_chain import ChainLLMSwitcher, ChainState, SKIP_THOUGHT_SIGNATURE, parse_chain
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


CHAIN = "groq:openai/gpt-oss-120b,gemini:gemini-3.5-flash,mistral:ministral-14b-latest"
KEYS = {"groq": "test-key", "gemini": "test-gemini", "mistral": "test-mistral"}


def build(handler=call_view, chain: ChainState | None = None):
    settings = Settings(groq_api_key="test-key", llm_chain=parse_chain(CHAIN, KEYS))
    return asyncio.run(build_pipeline(settings, CALL, FakeTransport(), api=api_with(handler), chain=chain))


def test_pipeline_params():
    task = build()
    procs = list(flatten(task.pipeline.processors))
    user = next(p for p in procs if isinstance(p, LLMUserAggregator))
    switcher = next(p for p in procs if isinstance(p, ChainLLMSwitcher))

    assert user._params.empty_user_turn is None
    assert user._params.vad_analyzer.params.stop_secs == 0.2
    assert user._params.user_turn_stop_timeout == 2.0
    assert user.context.get_messages()[0] == {"role": "assistant", "content": GREETING}
    assert len(switcher.llms) == 3
    for llm in switcher.llms:
        assert set(llm._functions) == {t["function"]["name"] for t in TOOL_SCHEMAS}
        assert len(llm._functions) == 7
        assert llm._settings.system_instruction == system_prompt(GREETING)
        assert llm._client.max_retries == 0
    groq, gemini, mistral = switcher.llms
    assert groq._settings.model == "openai/gpt-oss-120b" and groq._settings.extra == {"reasoning_effort": "low"}
    assert str(gemini._client.base_url).startswith("https://generativelanguage.googleapis.com/v1beta/openai")
    assert gemini._settings.model == "gemini-3.5-flash" and not gemini._settings.extra
    assert str(mistral._client.base_url).startswith("https://api.mistral.ai/v1")
    assert switcher.active_llm is groq


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


def _switcher(task) -> ChainLLMSwitcher:
    return next(p for p in flatten(task.pipeline.processors) if isinstance(p, ChainLLMSwitcher))


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


def test_llm_error_from_the_last_working_link_still_speaks_the_fallback():
    task = build()
    switcher = _switcher(task)
    queued = []

    async def record(frames):
        queued.extend(frames)

    task.queue_frames = record
    err = ErrorFrame(error="every link down")
    err.processor = switcher.llms[2]
    asyncio.run(_error_handler(task)(task, err))
    assert [f.text for f in queued] == [LLM_FALLBACK]


def _status_error(status: int, text: str, headers=None):
    import openai

    resp = httpx.Response(status, text=text, headers=headers or {},
                          request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"))
    cls = {429: openai.RateLimitError, 400: openai.BadRequestError}.get(status, openai.APIStatusError)
    return cls(text, response=resp, body=None)


def _error(service, exc):
    err = ErrorFrame(error=str(exc), exception=exc)
    err.processor = service
    return err


def _retries(switcher):
    sent = []
    for llm in switcher.llms:
        async def record(frame, direction=None, llm=llm):
            sent.append((llm, frame))
        llm.queue_frame = record
    return sent


def test_daily_cap_fails_over_to_the_next_link_and_retries_the_turn():
    from pipecat.frames.frames import LLMContextFrame
    from pipecat.processors.frame_processor import FrameDirection

    chain = ChainState(parse_chain(CHAIN, KEYS))
    task = build(chain=chain)
    switcher = _switcher(task)
    groq, gemini, _ = switcher.llms
    sent = _retries(switcher)
    switcher._context = object()
    exc = _status_error(429, "Rate limit reached on tokens per day (TPD)")

    async def run():
        await switcher.push_frame(_error(groq, exc), FrameDirection.UPSTREAM)

    asyncio.run(run())
    assert switcher.active_llm is gemini
    assert chain.status()["links"][0]["available"] is False
    retried = [f for s, f in sent if s is gemini and isinstance(f, LLMContextFrame)]
    assert len(retried) == 1 and retried[0].context is switcher._context


def test_tool_format_400_moves_on_without_cooldown_and_keeps_the_link_usable():
    chain = ChainState(parse_chain(CHAIN, KEYS))
    switcher = _switcher(build(chain=chain))
    groq, gemini, _ = switcher.llms
    exc = _status_error(400, '{"error":{"code":"tool_use_failed"}}')

    async def run():
        await groq.set_usable(False)
        return await switcher.strategy.handle_error(_error(groq, exc))

    assert asyncio.run(run()) is gemini
    assert groq.is_usable and chain.available(chain.links[0])


def test_no_switch_when_every_other_link_is_resting():
    chain = ChainState(parse_chain(CHAIN, KEYS))
    for link in chain.links[1:]:
        chain.fail(link, 3600, "429 per day", daily=True)
    switcher = _switcher(build(chain=chain))
    exc = _status_error(503, "overloaded")
    assert asyncio.run(switcher.strategy.handle_error(_error(switcher.llms[0], exc))) is None
    assert switcher.active_llm is switcher.llms[0]


def test_unrelated_errors_do_not_switch():
    chain = ChainState(parse_chain(CHAIN, KEYS))
    switcher = _switcher(build(chain=chain))
    exc = _status_error(400, "messages must not be empty")
    assert asyncio.run(switcher.strategy.handle_error(_error(switcher.llms[0], exc))) is None
    assert all(chain.available(l) for l in chain.links)


def test_new_turn_starts_on_the_first_rested_link():
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.frames.frames import LLMContextFrame
    from pipecat.processors.frame_processor import FrameDirection

    chain = ChainState(parse_chain(CHAIN, KEYS))
    chain.fail(chain.links[0], 3600, "429 per day", daily=True)
    switcher = _switcher(build(chain=chain))
    _retries(switcher)

    async def run():
        await switcher.process_frame(LLMContextFrame(LLMContext([])), FrameDirection.DOWNSTREAM)

    asyncio.run(run())
    assert switcher.active_llm is switcher.llms[1]


def test_live_requests_are_shaped_per_provider():
    switcher = _switcher(build())
    groq, gemini, mistral = switcher.llms
    history = [{"role": "assistant", "content": None, "reasoning": "x",
                "tool_calls": [{"id": "fc_long-groq-id", "type": "function",
                                "function": {"name": "get_policy", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "fc_long-groq-id", "content": "{}"}]
    params = {"messages": history, "tools": [], "tool_choice": None}
    g = gemini.build_chat_completion_params(dict(params))["messages"]
    assert g[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == SKIP_THOUGHT_SIGNATURE
    m = mistral.build_chat_completion_params(dict(params))["messages"]
    assert len(m[0]["tool_calls"][0]["id"]) == 9 and m[1]["tool_call_id"] == m[0]["tool_calls"][0]["id"]
    q = groq.build_chat_completion_params(dict(params))
    assert "reasoning" not in q["messages"][0] and q["reasoning_effort"] == "low"


def test_a_post_tool_inference_counts_as_a_fresh_attempt():
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.frames.frames import LLMContextFrame
    from pipecat.processors.frame_processor import FrameDirection

    switcher = _switcher(build())
    _retries(switcher)
    switcher._answered = True
    switcher.strategy.tried = {switcher.llms[1]}
    context = LLMContext([])

    async def run():
        await switcher.process_frame(LLMContextFrame(context), FrameDirection.UPSTREAM)

    asyncio.run(run())
    assert switcher._answered is False and switcher.strategy.tried == set() and switcher._context is context


def test_mistral_live_request_keeps_the_adapters_prefix_after_a_tool_result():
    from pipecat.processors.aggregators.llm_context import LLMContext

    mistral = _switcher(build()).llms[2]
    sent = {}

    class Completions:
        async def create(self, **params):
            sent.update(params)
            return object()

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    mistral._client = Client()
    context = LLMContext([
        {"role": "user", "content": "premium?"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "fc_long-groq-id", "type": "function", "function": {"name": "get_policy", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "fc_long-groq-id", "content": "{}"},
    ])
    asyncio.run(mistral.get_chat_completions(context))
    last = sent["messages"][-1]
    assert last["role"] == "assistant" and last["prefix"] is True
    assert len(sent["messages"][-2]["tool_call_id"]) == 9


def test_live_last_error_is_a_category_not_provider_text():
    chain = ChainState(parse_chain(CHAIN, KEYS))
    switcher = _switcher(build(chain=chain))
    exc = _status_error(429, "Rate limit reached on tokens per day in organization org_123")
    asyncio.run(switcher.strategy.handle_error(_error(switcher.llms[0], exc)))
    assert chain.status()["links"][0]["lastError"] == "429 daily limit"
