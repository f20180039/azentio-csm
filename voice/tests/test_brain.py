import asyncio
import json

import httpx

from app.api_client import RenewalsApi
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
    assert handoffs == [{"reason": "TOOL_LOOP_LIMIT", "callbackAt": None}]
    assert len(llm.seen) == 5


def test_malformed_argument_json_is_reported_to_model():
    llm = Scripted(tool_call("verify_identity", "{not json"), text("Sorry, could you repeat that?"))
    brain, calls = make(llm, ok)
    asyncio.run(brain.reply("hi"))
    tool_msg = [m for m in llm.seen[1] if m["role"] == "tool"][0]
    assert "BAD_ARGUMENTS" in tool_msg["content"]
    assert not any(p.endswith("/verify") for _, p, _ in calls)
