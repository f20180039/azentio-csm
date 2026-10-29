import asyncio
import json
from dataclasses import dataclass, field
from typing import Protocol

from .api_client import ApiUnavailable, RenewalsApi
from .tools import TOOL_SCHEMAS, run_tool

MAX_TOOL_ROUNDS = 5
LOOP_LIMIT_REPLY = "Let me get a colleague to help you."


class ChatClient(Protocol):
    async def complete(self, messages: list[dict], tools: list[dict]) -> dict: ...


@dataclass
class ToolTrace:
    name: str
    args: dict
    result: dict


@dataclass
class BrainTurn:
    text: str
    tool_calls: list[ToolTrace] = field(default_factory=list)


class CallBrain:
    def __init__(self, llm: ChatClient, api: RenewalsApi, call_id: str, system: str):
        self._llm = llm
        self._api = api
        self._call_id = call_id
        self._messages: list[dict] = [{"role": "system", "content": system}]
        self._lock = asyncio.Lock()
        self._memory: dict = {}
        self._posted_unanswered: str | None = None
        self.greeting: str | None = None

    async def say(self, text: str) -> None:
        self._messages.append({"role": "assistant", "content": text})
        await self._api.turn(self._call_id, "agent", text)

    async def reply(self, user_text: str) -> BrainTurn:
        async with self._lock:
            mark = len(self._messages)
            try:
                return await self._reply(user_text)
            except BaseException:
                del self._messages[mark:]
                raise

    async def _reply(self, user_text: str) -> BrainTurn:
        self._messages.append({"role": "user", "content": user_text})
        if self._posted_unanswered != user_text:  # a retry of a failed turn is the same customer line
            await self._api.turn(self._call_id, "customer", user_text)
            self._posted_unanswered = user_text
        traces: list[ToolTrace] = []
        for _ in range(MAX_TOOL_ROUNDS):
            msg = await self._llm.complete(self._messages, TOOL_SCHEMAS)
            calls = msg.get("tool_calls") or []
            if not calls:
                return await self._finish(msg.get("content") or "", traces)
            self._messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
            for call in calls:
                traces.append(await self._run(call))
                self._messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(traces[-1].result)}
                )
        return await self._handoff(LOOP_LIMIT_REPLY, "TOOL_LOOP_LIMIT", traces)

    async def _run(self, call: dict) -> ToolTrace:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as e:
            return ToolTrace(name, {}, {"error": "BAD_ARGUMENTS", "detail": f"invalid JSON: {e}"[:200]})
        return ToolTrace(name, args, await run_tool(self._api, self._call_id, name, args, self._memory))

    async def _handoff(self, text: str, reason: str, traces: list[ToolTrace]) -> BrainTurn:
        result = await self._api.handoff(self._call_id, reason)
        traces.append(ToolTrace("handoff_to_human", {"reason": reason}, result))
        return await self._finish(text, traces)

    async def _finish(self, text: str, traces: list[ToolTrace]) -> BrainTurn:
        self._posted_unanswered = None
        self._messages.append({"role": "assistant", "content": text})
        try:
            await self._api.turn(self._call_id, "agent", text)
        except ApiUnavailable:
            pass
        return BrainTurn(text, traces)
