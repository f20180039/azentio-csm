"""The front-desk agent's turn loop for typed and recorded-audio calls: tools against the bank simulator, every turn
recorded in Spring with the metadata the operator panel shows (intents, verification, tool trace, retrieved data, refs)."""
import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from loguru import logger

from .api_client import ApiUnavailable, SupportCallsApi
from .brain import ChatClient, ToolTrace
from .simulator_client import SimulatorClient
from .support_prompt import GREETING, support_prompt
from .support_tools import SUPPORT_TOOL_SCHEMAS, CallSession, run_support_tool

MAX_TOOL_ROUNDS = 6
LOOP_LIMIT_REPLY = "Let me get a colleague to help you with that."
RETRIEVED_LIMIT = 4000  # characters of a tool result kept for the panel

Classifier = Callable[[str, list[dict]], Awaitable[object]]

OUTCOME_BY_PREFIX = (("ESC-", "ESCALATED"), ("CMP-", "COMPLAINT_REGISTERED"), ("SR-", "TICKET_CREATED"), ("RQ-", "ROUTED"))


@dataclass
class SupportTurn:
    text: str
    tool_calls: list[ToolTrace] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    intent_source: str | None = None
    verified: bool = False
    locked: bool = False
    verify_failures: int = 0
    refs: list[str] = field(default_factory=list)
    model: str | None = None
    ended: bool = False

    def retrieved(self) -> dict:
        return {t.name: t.result for t in self.tool_calls}


def summarise(result: dict) -> str:
    if "error" in result:
        return f"error {result['error']}"
    if "ref" in result:
        return f"ref {result['ref']}"
    if isinstance(result.get("items"), list):
        ids = [next((str(v) for k, v in item.items() if k in {"ref", "loan_id", "account_id", "policy_no", "claim_no", "id", "n"}), "?")
               for item in result["items"] if isinstance(item, dict)]
        return f"{len(ids)} item(s): {', '.join(ids[:6])}" if ids else "no items"
    return ", ".join(sorted(result))[:120]


def _trim(result: dict) -> dict:
    raw = json.dumps(result)
    return result if len(raw) <= RETRIEVED_LIMIT else {"truncated": raw[:RETRIEVED_LIMIT]}


def outcome_for(refs: list[str]) -> str:
    for prefix, outcome in OUTCOME_BY_PREFIX:
        if any(r.startswith(prefix) for r in refs):
            return outcome
    return "RESOLVED"


class SupportBrain:
    def __init__(self, llm: ChatClient, sim: SimulatorClient, calls: SupportCallsApi | None, call: CallSession,
                 classify: Classifier | None = None):
        self._llm, self._sim, self._calls, self.call, self._classify = llm, sim, calls, call, classify
        self._messages: list[dict] = [{"role": "system", "content": support_prompt()}, {"role": "assistant", "content": GREETING}]
        self._lock = asyncio.Lock()
        self._seq = 0
        self._pending: set[asyncio.Task] = set()
        self.ended = False

    async def open(self) -> None:
        await self._record("agent", GREETING, {"greeting": True})

    async def reply(self, user_text: str) -> SupportTurn:
        async with self._lock:
            history = [m for m in self._messages if m["role"] in {"user", "assistant"} and m.get("content")][-4:]
            intents = asyncio.create_task(self._intents(user_text, history))
            customer_seq = await self._record("customer", user_text, self._verification())
            self._messages.append({"role": "user", "content": user_text})
            turn = await self._loop()
            self._messages.append({"role": "assistant", "content": turn.text})
            turn.verified, turn.refs = self.call.verified, list(self.call.refs)
            turn.locked, turn.verify_failures = self.call.locked, self.call.verify_failures
            await self._record("agent", turn.text, {"tool_trace": [{"name": t.name, "args": t.args, "result_summary": summarise(t.result)}
                                                                   for t in turn.tool_calls],
                                                    "retrieved": {t.name: _trim(t.result) for t in turn.tool_calls},
                                                    "refs": turn.refs, "verified": self.call.verified})
            found = await intents
            turn.intents, turn.intent_source = found
            await self._patch(customer_seq, {**self._verification(), "intents": turn.intents, "intent_source": turn.intent_source})
            return turn

    def mark_unheard(self) -> None:
        """The caller interrupted before hearing the last reply: keep it in context, but say it was never heard."""
        for m in reversed(self._messages):
            if m["role"] == "assistant" and m.get("content") and not m.get("tool_calls"):
                m["content"] = f"(Not heard: the caller interrupted before this was spoken.) {m['content']}"
                return

    async def no_speech(self, reason: str) -> None:
        """A customer turn with nothing to answer (silence, or noise the model turned into words): recorded, not replied to."""
        async with self._lock:
            await self._record("customer", "", {**self._verification(), "no_speech": True, "reason": reason, "intents": []})

    async def finish(self, outcome: str | None = None) -> str:
        outcome = outcome or outcome_for(self.call.refs)
        if self._calls:
            try:
                await self._calls.end(self.call.call_id, outcome)
            except ApiUnavailable as e:
                logger.warning(f"call end not recorded: {e}")
        return outcome

    async def _loop(self) -> SupportTurn:
        traces: list[ToolTrace] = []
        model = None
        for _ in range(MAX_TOOL_ROUNDS):
            msg = await self._llm.complete(self._messages, SUPPORT_TOOL_SCHEMAS)
            model = msg.get("model", model)
            calls = msg.get("tool_calls") or []
            if not calls:
                return SupportTurn(msg.get("content") or "", traces, model=model, ended=self.ended)
            self._messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
            for c in calls:
                trace = await self._run(c)
                traces.append(trace)
                self._messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(trace.result)})
        return SupportTurn(LOOP_LIMIT_REPLY, traces, model=model)

    async def _run(self, c: dict) -> ToolTrace:
        name = c["function"]["name"]
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as e:
            return ToolTrace(name, {}, {"error": "BAD_ARGUMENTS", "detail": f"invalid JSON: {e}"[:200]})
        if name == "end_call":
            self.ended = True
        return ToolTrace(name, args, await run_support_tool(self._sim, self.call, name, args))

    async def _intents(self, text: str, history: list[dict]) -> tuple[list[str], str | None]:
        if not self._classify:
            return [], None
        try:
            r = await self._classify(text, history)
            return [str(i) for i in r.intents], r.source
        except Exception as e:  # the classifier is advisory; a failure must never cost the reply
            logger.warning(f"intent classification failed: {e}")
            return [], None

    def _verification(self) -> dict:
        return {"verified": self.call.verified, "verify_failures": self.call.verify_failures, "locked": self.call.locked}

    async def _record(self, role: str, text: str, meta: dict) -> int:
        self._seq += 1
        if not self._calls:
            return self._seq
        try:
            out = await self._calls.turn(self.call.call_id, role, text, meta)
            if isinstance(out.get("seq"), int):
                self._seq = out["seq"]
        except ApiUnavailable as e:
            logger.warning(f"turn not recorded: {e}")
        return self._seq

    async def _patch(self, seq: int, meta: dict) -> None:
        if not self._calls:
            return
        try:
            await self._calls.patch_meta(self.call.call_id, seq, meta)
        except ApiUnavailable as e:
            logger.warning(f"turn meta not recorded: {e}")
