import asyncio
import json
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from .api_client import ApiUnavailable, RenewalsApi
from .config import Settings
from .tools import TOOL_SCHEMAS, run_tool

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_TOOL_ROUNDS = 5
LOOP_LIMIT_REPLY = "Let me get a colleague to help you."
UNAVAILABLE_REPLY = "I am having trouble reaching our system. Let me get a colleague to help you."


RETRY_STATUSES = {429, 503}


def _retry_delay(resp: httpx.Response) -> float:
    try:
        return min(max(float(resp.headers["retry-after"]), 0.0), 3.0)
    except (KeyError, ValueError):
        return 1.0


class ChatClient(Protocol):
    async def complete(self, messages: list[dict], tools: list[dict]) -> dict: ...


class GroqChatClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None, sleep=asyncio.sleep):
        self._sleep = sleep
        self._model = settings.llm_model
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {settings.groq_api_key}"}, timeout=30.0, transport=transport
        )

    async def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        body = {"model": self._model, "messages": messages, "tools": tools, "reasoning_effort": "low"}
        resp = await self._client.post(GROQ_URL, json=body)
        if resp.status_code in RETRY_STATUSES:
            await self._sleep(_retry_delay(resp))
            resp = await self._client.post(GROQ_URL, json=body)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]

    async def aclose(self) -> None:
        await self._client.aclose()


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

    async def say(self, text: str) -> None:
        self._messages.append({"role": "assistant", "content": text})
        await self._api.turn(self._call_id, "agent", text)

    async def reply(self, user_text: str) -> BrainTurn:
        self._messages.append({"role": "user", "content": user_text})
        await self._api.turn(self._call_id, "customer", user_text)
        traces: list[ToolTrace] = []
        try:
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
        except ApiUnavailable:
            return await self._finish(UNAVAILABLE_REPLY, traces)

    async def _run(self, call: dict) -> ToolTrace:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as e:
            return ToolTrace(name, {}, {"error": "BAD_ARGUMENTS", "detail": f"invalid JSON: {e}"[:200]})
        return ToolTrace(name, args, await run_tool(self._api, self._call_id, name, args))

    async def _handoff(self, text: str, reason: str, traces: list[ToolTrace]) -> BrainTurn:
        result = await self._api.handoff(self._call_id, reason)
        traces.append(ToolTrace("handoff_to_human", {"reason": reason}, result))
        return await self._finish(text, traces)

    async def _finish(self, text: str, traces: list[ToolTrace]) -> BrainTurn:
        self._messages.append({"role": "assistant", "content": text})
        try:
            await self._api.turn(self._call_id, "agent", text)
        except ApiUnavailable:
            pass
        return BrainTurn(text, traces)
