import asyncio
import json

import httpx
import pytest

from app.llm_chain import (
    SKIP_THOUGHT_SIGNATURE,
    ChainChatClient,
    ChainConfigError,
    ChainState,
    LLMUnavailable,
    cooldown_for,
    default_chain_spec,
    parse_chain,
    shape_messages,
)

KEYS = {"groq": "gk-secret", "gemini": "ge-secret", "mistral": "mi-secret"}
SPEC = "groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b,gemini:gemini-3.5-flash,mistral:ministral-14b-latest"


class Clock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def reply(content="hi", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return httpx.Response(200, json={"choices": [{"message": msg}]})


def client(handler, spec=SPEC, keys=KEYS, clock=None):
    clock = clock or Clock()
    state = ChainState(parse_chain(spec, keys), clock=clock)
    seen = []

    def wrapped(r: httpx.Request) -> httpx.Response:
        body = json.loads(r.content)
        seen.append((r.url.host, body["model"], body, r.headers.get("authorization")))
        return handler(r, body)

    return ChainChatClient(state.links, transport=httpx.MockTransport(wrapped), state=state), state, seen, clock


def test_default_spec_uses_provider_model_vars():
    assert default_chain_spec("", "") == (
        "groq:openai/gpt-oss-120b,gemini:gemini-3-flash-preview,groq:openai/gpt-oss-20b,mistral:mistral-small-latest,ollama:llama3.2"
    )
    spec = default_chain_spec("g-x", "m-y")
    assert "gemini:g-x" in spec and "mistral:m-y" in spec and spec.endswith("ollama:llama3.2")


def test_link_without_key_is_skipped():
    links = parse_chain(SPEC, {"groq": "k"})
    assert [l.name for l in links] == ["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b"]


def test_anthropic_is_rejected():
    with pytest.raises(ChainConfigError, match="anthropic"):
        parse_chain("groq:openai/gpt-oss-20b,anthropic:claude-x", {"groq": "k", "anthropic": "a"})


def test_unknown_provider_and_missing_model_are_rejected():
    with pytest.raises(ChainConfigError):
        parse_chain("openai:gpt-4o", KEYS)
    with pytest.raises(ChainConfigError):
        parse_chain("groq:", KEYS)


def test_cooldown_rules():
    assert cooldown_for(429, "Rate limit reached on tokens per day (TPD)", {"retry-after": "900"}) == 900
    assert cooldown_for(429, "Rate limit reached on tokens per day (TPD)", {}) == 3600
    assert cooldown_for(429, "Rate limit reached on requests per minute", {"retry-after": "7"}) == 7
    assert cooldown_for(429, "slow down", {"retry-after": "300"}) == 60
    assert cooldown_for(429, "slow down", {}) == 20
    assert cooldown_for(429, '{"error": {"details": [{"retryDelay": "34s"}]}}', {}) == 34
    assert cooldown_for(429, "Rate limit exceeded", {"x-ratelimit-limit-req-minute": "0"}) == 3600
    assert cooldown_for(503, "overloaded", {}) == 30
    assert cooldown_for(None, "timeout", {}, timeout=True) == 30
    assert cooldown_for(400, '{"error":{"code":"tool_use_failed"}}', {}) == 0
    assert cooldown_for(422, "Extra inputs are not permitted at tool_calls.0", {}) == 0
    assert cooldown_for(404, "model is no longer available", {}) == 3600
    assert cooldown_for(400, "messages must not be empty", {}) is None


def test_daily_cap_skips_link_until_cooldown_ends():
    def handler(r, body):
        if body["model"] == "openai/gpt-oss-120b":
            return httpx.Response(429, text="Rate limit reached on tokens per day (TPD)")
        return reply("from 20b")

    llm, state, seen, clock = client(handler)
    assert asyncio.run(llm.complete([{"role": "user", "content": "hi"}], []))["content"] == "from 20b"
    assert asyncio.run(llm.complete([{"role": "user", "content": "hi"}], []))["content"] == "from 20b"
    assert [m for _, m, _, _ in seen] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "openai/gpt-oss-20b"]
    assert state.status()["active"] == "groq:openai/gpt-oss-20b"
    clock.t += 3601
    asyncio.run(llm.complete([{"role": "user", "content": "hi"}], []))
    assert seen[-2][1] == "openai/gpt-oss-120b"


def test_per_minute_429_is_a_short_cooldown():
    def handler(r, body):
        if body["model"] == "openai/gpt-oss-120b":
            return httpx.Response(429, headers={"retry-after": "5"}, text="requests per minute")
        return reply()

    llm, state, seen, clock = client(handler)
    asyncio.run(llm.complete([], []))
    link = state.status()["links"][0]
    assert link["available"] is False and "429" in link["lastError"]
    clock.t += 6
    assert state.status()["links"][0]["available"] is True


def test_tool_format_400_falls_through_without_cooldown():
    def handler(r, body):
        if body["model"] == "openai/gpt-oss-120b":
            return httpx.Response(400, json={"error": {"code": "tool_use_failed", "message": "Failed to call a function"}})
        return reply("ok")

    llm, state, seen, _ = client(handler)
    assert asyncio.run(llm.complete([], []))["content"] == "ok"
    assert state.status()["links"][0]["available"] is True
    assert state.status()["links"][0]["cooldownUntil"] is None


def test_timeout_and_5xx_fail_over():
    def handler(r, body):
        if body["model"] == "openai/gpt-oss-120b":
            raise httpx.ReadTimeout("slow", request=r)
        if body["model"] == "openai/gpt-oss-20b":
            return httpx.Response(502)
        return reply("gemini")

    llm, state, seen, _ = client(handler)
    assert asyncio.run(llm.complete([], []))["content"] == "gemini"
    assert [l["available"] for l in state.status()["links"]] == [False, False, True, True]
    assert state.status()["active"] == "gemini:gemini-3.5-flash"


def test_other_client_errors_are_raised_not_swallowed():
    llm, _, seen, _ = client(lambda r, b: httpx.Response(400, text="messages must not be empty"))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(llm.complete([], []))
    assert len(seen) == 1


def test_all_links_cooling_raises_unavailable_with_daily_flag():
    llm, state, seen, _ = client(lambda r, b: httpx.Response(429, text="tokens per day"))
    with pytest.raises(LLMUnavailable) as e:
        asyncio.run(llm.complete([], []))
    assert e.value.daily is True and isinstance(e.value, httpx.HTTPError)
    n = len(seen)
    with pytest.raises(LLMUnavailable):
        asyncio.run(llm.complete([], []))
    assert len(seen) == n


def test_request_shape_per_provider():
    bodies = {}

    def handler(r, body):
        bodies[r.url.host] = (str(r.url), body, r.headers["authorization"])
        if r.url.host != "api.mistral.ai":
            return httpx.Response(503)
        return reply()

    llm, _, _, _ = client(handler, spec="groq:openai/gpt-oss-20b,groq:llama-x,gemini:g,mistral:m")
    asyncio.run(llm.complete([{"role": "user", "content": "hi"}], [{"type": "function"}]))
    groq_url, groq_body, groq_auth = bodies["api.groq.com"]
    assert groq_url == "https://api.groq.com/openai/v1/chat/completions" and groq_auth == "Bearer gk-secret"
    gem_url, gem_body, gem_auth = bodies["generativelanguage.googleapis.com"]
    assert gem_url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert gem_auth == "Bearer ge-secret" and "reasoning_effort" not in gem_body
    mis_url, mis_body, mis_auth = bodies["api.mistral.ai"]
    assert mis_url == "https://api.mistral.ai/v1/chat/completions" and mis_auth == "Bearer mi-secret"
    assert "reasoning_effort" not in mis_body and mis_body["tools"] == [{"type": "function"}]


def test_reasoning_effort_only_for_groq_gpt_oss():
    bodies = []

    def handler(r, body):
        bodies.append(body)
        return httpx.Response(503) if len(bodies) == 1 else reply()

    llm, _, _, _ = client(handler, spec="groq:openai/gpt-oss-20b,groq:llama-x")
    asyncio.run(llm.complete([], []))
    assert bodies[0]["reasoning_effort"] == "low" and "reasoning_effort" not in bodies[1]


HISTORY = [
    {"role": "user", "content": "premium?"},
    {"role": "assistant", "content": None, "reasoning": "think",
     "tool_calls": [{"id": "fc_7d1c2b3a-long-id", "type": "function",
                     "function": {"name": "get_policy", "arguments": "{}"},
                     "extra_content": {"google": {"thought_signature": "real"}}},
                    {"id": "abc123XYZ", "type": "function", "function": {"name": "list_allowed_options", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "fc_7d1c2b3a-long-id", "content": "{}"},
    {"role": "tool", "tool_call_id": "abc123XYZ", "content": "{}"},
]


def test_mistral_ids_are_normalised_and_map_back():
    shaped, back = shape_messages("mistral", HISTORY)
    ids = [c["id"] for c in shaped[1]["tool_calls"]]
    assert all(len(i) == 9 and i.isalnum() for i in ids)
    assert ids[1] == "abc123XYZ"
    assert [shaped[2]["tool_call_id"], shaped[3]["tool_call_id"]] == ids
    assert back[ids[0]] == "fc_7d1c2b3a-long-id"
    assert all("extra_content" not in c for c in shaped[1]["tool_calls"]) and "reasoning" not in shaped[1]
    assert shape_messages("mistral", HISTORY)[0] == shaped
    assert HISTORY[2]["tool_call_id"] == "fc_7d1c2b3a-long-id"


def test_mistral_reply_ids_are_mapped_back_into_history_ids():
    def handler(r, body):
        sent = body["messages"][1]["tool_calls"][0]["id"]
        return reply(None, [{"id": sent, "type": "function", "function": {"name": "get_policy", "arguments": "{}"}}])

    llm, _, _, _ = client(handler, spec="mistral:m")
    msg = asyncio.run(llm.complete(HISTORY, []))
    assert msg["tool_calls"][0]["id"] == "fc_7d1c2b3a-long-id"


def test_gemini_keeps_real_signatures_and_stubs_missing_ones():
    shaped, _ = shape_messages("gemini", HISTORY)
    sigs = [c["extra_content"]["google"]["thought_signature"] for c in shaped[1]["tool_calls"]]
    assert sigs == ["real", SKIP_THOUGHT_SIGNATURE]
    groq, _ = shape_messages("groq", HISTORY)
    assert all("extra_content" not in c for c in groq[1]["tool_calls"])
    assert groq[1]["tool_calls"][0]["id"] == "fc_7d1c2b3a-long-id"


def test_reply_is_normalised_and_keeps_gemini_signature():
    def handler(r, body):
        return reply(None, [{"id": "call_1", "type": "function", "index": 0,
                             "function": {"name": "get_policy", "arguments": "{}"},
                             "extra_content": {"google": {"thought_signature": "sig"}}}])

    llm, _, _, _ = client(handler, spec="gemini:g")
    msg = asyncio.run(llm.complete([], []))
    assert msg == {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "get_policy", "arguments": "{}"},
         "extra_content": {"google": {"thought_signature": "sig"}}}], "model": "gemini:g"}


def test_status_has_no_secrets():
    def handler(r, body):
        return httpx.Response(401, text="Invalid API Key gk-secret")

    llm, state, _, _ = client(handler, spec="groq:openai/gpt-oss-20b")
    with pytest.raises(LLMUnavailable):
        asyncio.run(llm.complete([], []))
    status = state.status()
    text = json.dumps(status)
    assert "secret" not in text
    assert status["active"] is None
    assert set(status["links"][0]) == {"name", "available", "cooldownUntil", "lastError"}
    assert status["links"][0]["cooldownUntil"].endswith("Z")


def test_gemini_stream_gets_tool_call_indexes_one_call_per_chunk():
    from openai.types.chat import ChatCompletionChunk

    from app.llm_chain import index_tool_call_stream

    def chunk(*calls):
        c = ChatCompletionChunk.model_validate({
            "id": "x", "created": 0, "model": "g", "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": 0, "id": i, "type": "function", "function": {"name": n, "arguments": "{}"}} for i, n in calls]}}]})
        for t in c.choices[0].delta.tool_calls:
            t.index = None  # as Gemini streams them; the SDK does not validate stream chunks
        return c

    class Stream:
        closed = False

        def __init__(self, chunks):
            self.chunks = chunks

        async def __aiter__(self):
            for c in self.chunks:
                yield c

        async def close(self):
            Stream.closed = True

    async def collect():
        out = []
        async for c in index_tool_call_stream(Stream([chunk(("a", "get_policy")), chunk(("b", "x"), ("c", "y"))])):
            out.append([(t.index, t.id) for t in c.choices[0].delta.tool_calls])
        return out

    assert asyncio.run(collect()) == [[(0, "a")], [(1, "b")], [(2, "c")]]
    assert Stream.closed


def test_mistral_expected_last_role_400_is_a_tool_format_error():
    body = '{"message":"Expected last role User or Tool (or Assistant with prefix True) for serving but got assistant"}'
    assert cooldown_for(400, body, {}) == 0


def test_mistral_keeps_prefix_other_providers_drop_it():
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": " ", "prefix": True}]
    assert shape_messages("mistral", msgs)[0][1]["prefix"] is True
    assert "prefix" not in shape_messages("groq", msgs)[0][1]
    assert "prefix" not in shape_messages("gemini", msgs)[0][1]


def test_a_failure_never_shortens_an_existing_cooldown():
    clock = Clock()
    state = ChainState(parse_chain("groq:a", KEYS), clock=clock)
    link = state.links[0]
    state.fail(link, 3600, "429 daily limit", daily=True)
    state.fail(link, 20, "429 rate limit")
    state.fail(link, 0, "400 tool-call format")
    clock.t += 1000
    assert state.available(link) is False
    clock.t += 2601
    assert state.available(link) is True


def test_last_error_is_status_and_category_only():
    cases = [
        (429, "Rate limit reached on tokens per day (TPD) in organization org_123", {}, "429 daily limit"),
        (429, "slow down org_123", {"retry-after": "3"}, "429 rate limit"),
        (503, "overloaded org_123", {}, "503 server error"),
        (404, "models/gemini-2.5-flash is no longer available", {}, "404 model not found"),
        (401, "Invalid API Key", {}, "401 unauthorized"),
        (403, "tier_not_allowed", {}, "403 forbidden"),
        (400, '{"error":{"code":"tool_use_failed"}}', {}, "400 tool-call format"),
    ]
    for status, body, headers, expected in cases:
        def handler(r, b, status=status, body=body, headers=headers):
            return httpx.Response(status, text=body, headers=headers)

        llm, state, _, _ = client(handler, spec="groq:a")
        with pytest.raises(LLMUnavailable):
            asyncio.run(llm.complete([], []))
        assert state.status()["links"][0]["lastError"] == expected

    def timeout(r, b):
        raise httpx.ReadTimeout("slow", request=r)

    llm, state, _, _ = client(timeout, spec="groq:a")
    with pytest.raises(LLMUnavailable):
        asyncio.run(llm.complete([], []))
    assert state.status()["links"][0]["lastError"] == "timeout"


def test_each_reply_names_the_link_that_answered_it():
    def handler(r, body):
        if body["model"] == "openai/gpt-oss-120b":
            return httpx.Response(503)
        return reply("ok")

    llm, *_ = client(handler)
    out = asyncio.run(llm.complete([], []))
    assert out["model"] == "groq:openai/gpt-oss-20b" and out["content"] == "ok"
