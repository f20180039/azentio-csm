import asyncio
import json

import httpx

from app.api_client import ApiUnavailable, RenewalsApi
from app.brain import CallBrain
from app.config import Settings

CALL = "11111111-1111-1111-1111-111111111111"


class Scripted:
    def __init__(self, *responses):
        self.queue = list(responses)
        self.seen: list[list[dict]] = []

    async def complete(self, messages, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        return self.queue.pop(0)


def tool_call(name: str, args, call_id: str = "c1") -> dict:
    raw = args if isinstance(args, str) else json.dumps(args)
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}],
    }


def text(t: str) -> dict:
    return {"role": "assistant", "content": t}


def make(llm, handler):
    calls = []

    def wrapped(r: httpx.Request) -> httpx.Response:
        calls.append((r.method, r.url.path, json.loads(r.content) if r.content else None))
        return handler(r)

    api = RenewalsApi(Settings(), transport=httpx.MockTransport(wrapped))
    return CallBrain(llm, api, CALL, "SYSTEM"), calls


def ok(r):
    return httpx.Response(200, json={"verified": True})


def test_tool_round_then_text():
    llm = Scripted(tool_call("verify_identity", {"date_of_birth": "1980-03-14"}), text("Thanks, you are verified."))
    brain, calls = make(llm, ok)
    turn = asyncio.run(brain.reply("My birthday is 14 March 1980"))
    assert turn.text == "Thanks, you are verified."
    assert turn.tool_calls[0].name == "verify_identity"
    assert ("POST", f"/api/v1/renewals/calls/{CALL}/verify", {"dateOfBirth": "1980-03-14"}) in calls
    roles = [(p, b["role"]) for _, p, b in calls if p.endswith("/turns")]
    assert [r for _, r in roles] == ["customer", "agent"]


def test_refusal_reaches_model():
    def handler(r):
        if r.url.path.endswith("/turns"):
            return httpx.Response(200, json={})
        return httpx.Response(422, json={"detail": "OUTSIDE_PLAYBOOK"})

    llm = Scripted(tool_call("quote_renewal", {"drop_addons": [], "payment_plan": "annual", "discount_percent": 40}),
                   text("I cannot offer that."))
    brain, _ = make(llm, handler)
    asyncio.run(brain.reply("give me 40 percent"))
    tool_msgs = [m for m in llm.seen[1] if m["role"] == "tool"]
    assert "OUTSIDE_PLAYBOOK" in tool_msgs[0]["content"]
    assert tool_msgs[0]["tool_call_id"] == "c1"


def test_tool_loop_limit_hands_off():
    llm = Scripted(*[tool_call("get_policy", {}, f"c{i}") for i in range(6)])
    brain, calls = make(llm, ok)
    turn = asyncio.run(brain.reply("hello"))
    assert turn.text == "Let me get a colleague to help you."
    handoffs = [b for _, p, b in calls if p.endswith("/handoff")]
    assert handoffs == [{"reason": "TOOL_LOOP_LIMIT"}]
    assert len(llm.seen) == 5


def test_malformed_argument_json_is_reported_to_model():
    llm = Scripted(tool_call("verify_identity", "{not json"), text("Sorry, could you repeat that?"))
    brain, calls = make(llm, ok)
    asyncio.run(brain.reply("hi"))
    tool_msg = [m for m in llm.seen[1] if m["role"] == "tool"][0]
    assert "BAD_ARGUMENTS" in tool_msg["content"]
    assert not any(p.endswith("/verify") for _, p, _ in calls)


def groq(handler, sleeps):
    from app.brain import GroqChatClient

    async def sleep(s):
        sleeps.append(s)

    return GroqChatClient(Settings(groq_api_key="k"), transport=httpx.MockTransport(handler), sleep=sleep)


def test_groq_retries_once_after_retry_after_capped():
    n, sleeps = [], []

    def handler(r):
        n.append(1)
        if len(n) == 1:
            return httpx.Response(429, headers={"retry-after": "10"})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "hi"}}]})

    msg = asyncio.run(groq(handler, sleeps).complete([], []))
    assert msg["content"] == "hi" and len(n) == 2 and sleeps == [3.0]


def test_groq_fails_after_second_503_default_delay():
    n, sleeps = [], []

    def handler(r):
        n.append(1)
        return httpx.Response(503)

    client = groq(handler, sleeps)
    try:
        asyncio.run(client.complete([], []))
        raise AssertionError("expected failure")
    except httpx.HTTPStatusError:
        pass
    assert len(n) == 2 and sleeps == [1.0]


def assert_valid_history(messages):
    for i, m in enumerate(messages):
        if m["role"] == "assistant" and m.get("tool_calls"):
            ids = [c["id"] for c in m["tool_calls"]]
            replies = [x["tool_call_id"] for x in messages[i + 1:i + 1 + len(ids)] if x["role"] == "tool"]
            assert replies == ids


def test_failed_turn_leaves_no_dangling_tool_calls():
    two = tool_call("get_policy", {}, "a")
    two["tool_calls"].append(tool_call("list_allowed_options", {}, "b")["tool_calls"][0])
    llm = Scripted(two, text("Hello again."))
    state = {"fail": True}

    def handler(r):
        if state["fail"] and r.url.path.endswith("/policy"):
            return httpx.Response(503)
        return httpx.Response(200, json={})

    brain, _ = make(llm, handler)
    try:
        asyncio.run(brain.reply("first"))
        raise AssertionError("expected ApiUnavailable")
    except ApiUnavailable:
        pass
    state["fail"] = False
    llm.queue = [text("Fine.")]
    asyncio.run(brain.reply("second"))
    assert_valid_history(llm.seen[-1])
    assert [m["content"] for m in llm.seen[-1] if m["role"] == "user"] == ["second"]


def test_concurrent_replies_do_not_interleave():
    class Slow:
        def __init__(self):
            self.seen = []

        async def complete(self, messages, tools):
            self.seen.append([m["role"] + ":" + str(m["content"]) for m in messages])
            await asyncio.sleep(0.05)
            return text("ok")

    llm = Slow()
    brain, _ = make(llm, ok)

    async def both():
        await asyncio.gather(brain.reply("one"), brain.reply("two"))

    asyncio.run(both())
    assert llm.seen[0] == ["system:SYSTEM", "user:one"]
    assert llm.seen[1] == ["system:SYSTEM", "user:one", "assistant:ok", "user:two"]


def test_retried_turn_posts_the_customer_line_once():
    class FlakyThenOk:
        def __init__(self):
            self.n = 0

        async def complete(self, messages, tools):
            self.n += 1
            if self.n == 1:
                raise httpx.HTTPStatusError("429", request=httpx.Request("POST", "x"), response=httpx.Response(429))
            return text("Hello again.")

    brain, calls = make(FlakyThenOk(), ok)
    try:
        asyncio.run(brain.reply("my date of birth is 14 March 1980"))
    except httpx.HTTPError:
        pass
    asyncio.run(brain.reply("my date of birth is 14 March 1980"))
    turns = [b["role"] for _, p, b in calls if p.endswith("/turns")]
    assert turns == ["customer", "agent"]
    asyncio.run(brain.reply("my date of birth is 14 March 1980"))
    assert [b["role"] for _, p, b in calls if p.endswith("/turns")] == ["customer", "agent", "customer", "agent"]


def test_brain_remembers_the_premium_for_a_refused_discount():
    def handler(r):
        if r.url.path.endswith("/policy"):
            return httpx.Response(200, json={"renewalPremium": 2094})
        if r.url.path.endswith("/quote"):
            return httpx.Response(422, json={"detail": "OUTSIDE_PLAYBOOK"})
        return httpx.Response(200, json={})

    llm = Scripted(tool_call("get_policy", {}, "c1"), text("It is two thousand and ninety-four rupees."),
                   tool_call("quote_renewal", {"discount_percent": 20}, "c2"), text("No discount, sorry."))
    brain, _ = make(llm, handler)
    asyncio.run(brain.reply("what is my premium"))
    asyncio.run(brain.reply("20 percent off please"))
    tool_msg = [m for m in llm.seen[-1] if m["role"] == "tool"][-1]
    assert "unchanged at two thousand and ninety-four rupees" in tool_msg["content"]
