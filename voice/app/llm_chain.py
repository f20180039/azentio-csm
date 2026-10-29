"""Ordered chain of free OpenAI-compatible models: the first link not cooling down answers."""

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import openai
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, FunctionCallsStartedFrame, LLMContextFrame, LLMTextFrame
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.service_switcher import ServiceSwitcherStrategyManual
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.llm_service import LLMService
from pipecat.services.mistral.llm import MistralLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.utils.errors import extract_http_status_code

PROVIDERS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "mistral": "https://api.mistral.ai/v1",
}
SKIP_THOUGHT_SIGNATURE = "skip_thought_signature_validator"
TIMEOUT_SECS = 30.0

DAILY_COOLDOWN = 3600.0
MINUTE_COOLDOWN_CAP = 60.0
MINUTE_COOLDOWN = 20.0
SERVER_COOLDOWN = 30.0
UNUSABLE_COOLDOWN = 3600.0

_DAILY = re.compile(r"per ?day|\bTPD\b|\bRPD\b", re.I)
_TOOL_FORMAT = re.compile(r"tool_use_failed|failed to call a function|tool[_ ]?call|function[_ ]?call|thought_signature", re.I)
_RETRY_DELAY = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')
_MISTRAL_ID = re.compile(r"[A-Za-z0-9]{9}")
_MESSAGE_KEYS = ("role", "content", "tool_calls", "tool_call_id", "name")


class ChainConfigError(ValueError):
    pass


class LLMUnavailable(httpx.HTTPError):
    def __init__(self, message: str, daily: bool):
        super().__init__(message)
        self.daily = daily


@dataclass(frozen=True)
class Link:
    provider: str
    model: str
    api_key: str = field(repr=False)

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def base_url(self) -> str:
        return PROVIDERS[self.provider]

    @property
    def reasoning_effort(self) -> str | None:
        return "low" if self.provider == "groq" and "gpt-oss" in self.model else None


def default_chain_spec(gemini_model: str, mistral_model: str) -> str:
    return (
        "groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b,"
        f"gemini:{gemini_model or 'gemini-2.5-flash'},mistral:{mistral_model or 'mistral-small-latest'}"
    )


def parse_chain(spec: str, keys: dict[str, str]) -> tuple[Link, ...]:
    links = []
    for item in (s.strip() for s in spec.split(",")):
        if not item:
            continue
        provider, _, model = item.partition(":")
        provider, model = provider.strip().lower(), model.strip()
        if provider == "anthropic":
            raise ChainConfigError("VOICE_LLM_CHAIN: anthropic is not allowed for the voice agent")
        if provider not in PROVIDERS:
            raise ChainConfigError(f"VOICE_LLM_CHAIN: unknown provider {provider!r} (use {', '.join(PROVIDERS)})")
        if not model:
            raise ChainConfigError(f"VOICE_LLM_CHAIN: {item!r} names no model")
        if not keys.get(provider):
            logger.warning(f"LLM chain: skipping {item}, no API key for {provider}")
            continue
        links.append(Link(provider, model, keys[provider]))
    return tuple(links)


def cooldown_for(status: int | None, body: str, headers, timeout: bool = False) -> float | None:
    """Seconds to rest a link after a failure, 0 to just try the next one, None if no other link would help."""
    if timeout:
        return SERVER_COOLDOWN
    if status is None:
        return None
    if status == 429:
        hint = _RETRY_DELAY.search(body)  # Gemini puts it in the body
        retry_after = _float(headers.get("retry-after") or (hint.group(1) if hint else None))
        if is_daily_cap(status, body, headers):
            return retry_after or DAILY_COOLDOWN
        return min(retry_after, MINUTE_COOLDOWN_CAP) if retry_after is not None else MINUTE_COOLDOWN
    if status >= 500:
        return SERVER_COOLDOWN
    if status in (401, 403, 404):
        return UNUSABLE_COOLDOWN
    if status in (400, 422) and _TOOL_FORMAT.search(body):
        return 0.0
    return None


def is_daily_cap(status: int | None, body: str, headers) -> bool:
    return status == 429 and bool(_DAILY.search(body) or headers.get("x-ratelimit-limit-req-minute") == "0")


def _float(value) -> float | None:
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return None


def _mistral_id(call_id: str) -> str:
    if _MISTRAL_ID.fullmatch(call_id):
        return call_id
    return hashlib.sha256(call_id.encode()).hexdigest()[:9]


def shape_messages(provider: str, messages: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """OpenAI-format history as `provider` accepts it, plus a map from rewritten tool-call ids to the originals."""
    out, back = [], {}

    def tool_id(call_id: str) -> str:
        if provider != "mistral":
            return call_id
        new = _mistral_id(call_id)
        back[new] = call_id
        return new

    for m in messages:
        shaped = {k: m[k] for k in _MESSAGE_KEYS if k in m}
        if m.get("tool_calls"):
            shaped["tool_calls"] = [_shape_call(provider, c, tool_id) for c in m["tool_calls"]]
        if "tool_call_id" in m:
            shaped["tool_call_id"] = tool_id(m["tool_call_id"])
        out.append(shaped)
    return out, back


def _shape_call(provider: str, call: dict, tool_id) -> dict:
    fn = call.get("function") or {}
    shaped = {"id": tool_id(call["id"]), "type": "function",
              "function": {"name": fn.get("name"), "arguments": fn.get("arguments") or "{}"}}
    if provider == "gemini":
        shaped["extra_content"] = call.get("extra_content") or {"google": {"thought_signature": SKIP_THOUGHT_SIGNATURE}}
    return shaped


def _normalise_reply(msg: dict, back: dict[str, str]) -> dict:
    out = {"role": "assistant", "content": msg.get("content")}
    calls = []
    for c in msg.get("tool_calls") or []:
        fn = c.get("function") or {}
        args = fn.get("arguments")
        call = {"id": back.get(c.get("id"), c.get("id")) or f"call{uuid4().hex[:8]}", "type": "function",
                "function": {"name": fn.get("name"), "arguments": args if isinstance(args, str) else json.dumps(args or {})}}
        if c.get("extra_content"):
            call["extra_content"] = c["extra_content"]
        calls.append(call)
    if calls:
        out["tool_calls"] = calls
    return out


@dataclass
class _Health:
    cooldown_until: float | None = None
    last_error: str | None = None
    daily: bool = False


class ChainState:
    """Which links are resting and which one answered last. Shared by the text brain and live calls."""

    def __init__(self, links: tuple[Link, ...], clock=time.time):
        self.links = links
        self._clock = clock
        self._health = {l.name: _Health() for l in links}
        self._secrets = [l.api_key for l in links if l.api_key]
        self.active: str | None = None

    def available(self, link: Link) -> bool:
        until = self._health[link.name].cooldown_until
        return until is None or until <= self._clock()

    def candidates(self) -> list[Link]:
        return [l for l in self.links if self.available(l)]

    def fail(self, link: Link, cooldown: float, error: str, daily: bool = False) -> None:
        h = self._health[link.name]
        h.last_error = self._redact(error)[:200]
        h.daily = daily
        h.cooldown_until = self._clock() + cooldown if cooldown > 0 else h.cooldown_until
        logger.warning(f"LLM chain: {link.name} failed ({h.last_error}); resting {cooldown:.0f}s")

    def answered(self, link: Link) -> None:
        self._health[link.name].daily = False
        if self.active != link.name:
            logger.info(f"LLM chain: {link.name} answering")
        self.active = link.name

    def all_daily(self) -> bool:
        return bool(self.links) and all(self._health[l.name].daily for l in self.links)

    def status(self) -> dict:
        now = self._clock()
        links = []
        for l in self.links:
            h = self._health[l.name]
            resting = h.cooldown_until is not None and h.cooldown_until > now
            until = datetime.fromtimestamp(h.cooldown_until, timezone.utc) if resting else None
            links.append({
                "name": l.name,
                "available": not resting,
                "cooldownUntil": until.isoformat(timespec="seconds").replace("+00:00", "Z") if until else None,
                "lastError": h.last_error,
            })
        return {"active": self.active, "links": links}

    def _redact(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "***")
        return text


class ChainChatClient:
    """ChatClient over the chain: on a rate limit, outage, timeout or tool-format refusal the next link answers."""

    def __init__(self, links: tuple[Link, ...], transport: httpx.AsyncBaseTransport | None = None,
                 state: ChainState | None = None):
        self.state = state or ChainState(links)
        self._client = httpx.AsyncClient(timeout=TIMEOUT_SECS, transport=transport)

    async def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        for link in self.state.candidates():
            shaped, back = shape_messages(link.provider, messages)
            body = {"model": link.model, "messages": shaped, "tools": tools}
            if link.reasoning_effort:
                body["reasoning_effort"] = link.reasoning_effort
            try:
                resp = await self._client.post(f"{link.base_url}/chat/completions", json=body,
                                               headers={"Authorization": f"Bearer {link.api_key}"})
            except httpx.TimeoutException:
                self.state.fail(link, cooldown_for(None, "", {}, timeout=True), "timeout")
                continue
            except httpx.TransportError as e:
                self.state.fail(link, SERVER_COOLDOWN, f"connection error: {type(e).__name__}")
                continue
            if resp.status_code >= 400:
                cooldown = cooldown_for(resp.status_code, resp.text, resp.headers)
                if cooldown is None:
                    resp.raise_for_status()
                self.state.fail(link, cooldown, f"{resp.status_code} {resp.text[:160]}",
                                daily=is_daily_cap(resp.status_code, resp.text, resp.headers))
                continue
            self.state.answered(link)
            return _normalise_reply(resp.json()["choices"][0]["message"], back)
        raise LLMUnavailable("every model in the chain is unavailable", daily=self.state.all_daily())

    async def aclose(self) -> None:
        await self._client.aclose()


# ---- Live calls: one Pipecat LLM service per link behind an LLMSwitcher ----------------------------

LIVE_TIMEOUT_SECS = 15.0


class _Shaped:
    _chain_provider = ""

    def build_chat_completion_params(self, params_from_context) -> dict:
        params = super().build_chat_completion_params(params_from_context)
        params["messages"], _ = shape_messages(self._chain_provider, list(params["messages"]))
        return params


class _GroqLink(_Shaped, GroqLLMService):
    _chain_provider = "groq"


class _GeminiLink(_Shaped, OpenAILLMService):
    _chain_provider = "gemini"

    async def get_chat_completions(self, context):
        return index_tool_call_stream(await super().get_chat_completions(context))


async def index_tool_call_stream(stream):
    """Gemini streams each tool call whole but with no `index`; Pipecat reads one indexed call per chunk."""
    ids: dict[str, int] = {}
    try:
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            calls = (delta.tool_calls or []) if delta else []
            if not calls:
                yield chunk
                continue
            for call in calls:
                if call.index is None:
                    call.index = ids.setdefault(call.id or f"#{len(ids)}", len(ids))
                one = chunk.model_copy(deep=True)
                one.choices[0].delta.tool_calls = [call]
                yield one
    finally:
        await stream.close()


class _MistralLink(_Shaped, MistralLLMService):
    _chain_provider = "mistral"


def build_live_llm(link: Link, system_instruction: str) -> LLMService:
    extra = {"reasoning_effort": link.reasoning_effort} if link.reasoning_effort else {}
    if link.provider == "groq":
        llm = _GroqLink(api_key=link.api_key, settings=_GroqLink.Settings(
            model=link.model, system_instruction=system_instruction, extra=extra))
    elif link.provider == "gemini":
        llm = _GeminiLink(api_key=link.api_key, base_url=link.base_url, settings=_GeminiLink.Settings(
            model=link.model, system_instruction=system_instruction))
    else:
        llm = _MistralLink(api_key=link.api_key, settings=_MistralLink.Settings(
            model=link.model, system_instruction=system_instruction))
    # Failing over beats the SDK's own retries, which wait out a rate limit the next link doesn't have.
    llm._client = llm._client.with_options(max_retries=0, timeout=LIVE_TIMEOUT_SECS)
    return llm


def exception_cooldown(exc: BaseException | None) -> tuple[float | None, str, bool]:
    """(cooldown, short error, daily cap) for an exception a live LLM service reported."""
    if isinstance(exc, (openai.APITimeoutError, TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)):
        return SERVER_COOLDOWN, "timeout", False
    if isinstance(exc, openai.APIConnectionError):
        return SERVER_COOLDOWN, "connection error", False
    status = extract_http_status_code(exc) if exc is not None else None
    response = getattr(exc, "response", None)
    try:
        body = response.text if response is not None else str(exc)
    except Exception:
        body = str(exc)
    headers = getattr(response, "headers", None) or {}
    return cooldown_for(status, body, headers), f"{status} {body[:160]}", is_daily_cap(status, body, headers)


class ChainFailoverStrategy(ServiceSwitcherStrategyManual):
    """Pipecat's failover only leaves a service it judges dead; this one rests a link on a rate limit too."""

    def bind(self, chain: ChainState, links: tuple[Link, ...]) -> None:
        self.chain, self.links, self.tried = chain, links, set()

    def link_of(self, service: FrameProcessor) -> Link:
        return self.links[self.services.index(service)]

    def preferred(self, exclude=()) -> FrameProcessor | None:
        for service, link in zip(self.services, self.links):
            if service not in exclude and self.chain.available(link):
                return service
        return None

    async def activate(self, service: FrameProcessor) -> FrameProcessor | None:
        return await self._set_active_if_available(service)

    async def handle_error(self, error: ErrorFrame) -> FrameProcessor | None:
        failed = error.processor or self.active_service
        if failed not in self.services:
            return None
        if not failed.is_usable:  # a 4xx costs a Pipecat service its usability for good; the chain decides instead
            await failed.set_usable(True)
        cooldown, summary, daily = exception_cooldown(error.exception)
        if cooldown is None:
            return None
        self.chain.fail(self.link_of(failed), cooldown, summary, daily=daily)
        self.tried.add(failed)
        nxt = self.preferred(exclude=self.tried)
        return await self.activate(nxt) if nxt is not None else None


class ChainLLMSwitcher(LLMSwitcher):
    """Starts each turn on the first rested link; on a failover, re-runs the failed turn on the new link."""

    def __init__(self, llms: list[LLMService], links: tuple[Link, ...], chain: ChainState):
        super().__init__(llms, strategy_type=ChainFailoverStrategy)
        self.strategy.bind(chain, links)
        self._chain = chain
        self._context = None
        self._answered = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, LLMContextFrame):  # downstream for a new turn, upstream after a tool round
            self._context, self._answered, self.strategy.tried = frame.context, False, set()
            preferred = self.strategy.preferred()
            if preferred is not None and preferred is not self.strategy.active_service:
                await self.strategy.activate(preferred)
        await super().process_frame(frame, direction)

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        active = self.strategy.active_service
        if isinstance(frame, (LLMTextFrame, FunctionCallsStartedFrame)) and not self._answered:
            self._answered = True
            self._chain.answered(self.strategy.link_of(active))
        if isinstance(frame, ErrorFrame) and not frame.fatal and frame.processor is active:
            await super().push_frame(frame, direction)
            now = self.strategy.active_service
            if now is not active and self._context is not None and not self._answered:
                await now.queue_frame(LLMContextFrame(self._context))
            return
        await super().push_frame(frame, direction)


def build_live_switcher(chain: ChainState, system_instruction: str) -> ChainLLMSwitcher:
    if not chain.links:
        raise ChainConfigError("VOICE_LLM_CHAIN has no usable link (no API keys?)")
    llms = [build_live_llm(link, system_instruction) for link in chain.links]
    return ChainLLMSwitcher(llms, chain.links, chain)
