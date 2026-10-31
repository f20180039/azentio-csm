"""The front-desk agent's turn loop for typed and recorded-audio calls: tools against the bank simulator, every turn
recorded in Spring with the metadata the operator panel shows (intents, verification, tool trace, retrieved data, refs)."""
import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from loguru import logger

from . import recordings
from .api_client import ApiUnavailable, SupportCallsApi
from .brain import ChatClient, ToolTrace
from .identity import digit_run, extract_dob, extract_mobile, is_mobile_attempt, unexplained_fields
from .intents import Intent
from .simulator_client import SimulatorClient
from .speech import normalise_refs, normalise_spoken_digits, script_language
from .support_prompt import GREETING, support_prompt
from .support_tools import SUPPORT_TOOL_SCHEMAS, UNAUTHORISED, CallSession, ComplaintCategory, Severity, run_support_tool
from .vocab import (HTTP_ERROR_PREFIX, EscalationTrigger, IntentSource, MetaKey, OpOutcome, Outcome, RefPrefix, SpeechLanguage, SupportTool,
                    ToolError, TurnRole, VerifyField)

MAX_TOOL_ROUNDS = 6
UNCLEAR_BEFORE_ESCALATION = 3  # customer turns in a row understood as nothing but UNCLEAR before a person takes over
LOOP_LIMIT_REPLY = "Let me get a colleague to help you with that."
RETRIEVED_LIMIT = 4000  # characters of a tool result kept for the panel
HISTORY_TURNS = 6  # caller turns of history sent to the model (free tiers cap tokens per minute)
OLD_TOOL_RESULT_CHARS = 600  # tool results from earlier turns are shortened; the current turn's stay whole

Classifier = Callable[[str, list[dict]], Awaitable[object]]
Translator = Callable[[str], Awaitable[str | None]]
TRANSLATE_GRACE_SECS = 3  # finish() waits this long for pending translations; later ones still land (patch_meta works after the end)
TRANSLATED_SCRIPTS = frozenset({SpeechLanguage.KANNADA, SpeechLanguage.HINDI})

OUTCOME_BY_PREFIX = ((RefPrefix.ESCALATION, Outcome.ESCALATED), (RefPrefix.COMPLAINT, Outcome.COMPLAINT_REGISTERED),
                     (RefPrefix.SERVICE_REQUEST, Outcome.TICKET_CREATED), (RefPrefix.ROUTED, Outcome.ROUTED))

CORRECTION_MAX_CHARS = 2000  # the core API's limit on a transcript correction; the voice service accepts the same text
CORRECTION_NOTE = ('(Correction from the bank\'s reviewer for an earlier caller turn: the caller actually said: "{text}". '
                   "Use this instead of what was heard.)")
HEARD_KEY = {VerifyField.MOBILE: "mobile", VerifyField.DOB: "dob"}  # apply_correction's answer: which identity fields it filled


def _clean_reply(text: str) -> str:
    """Strips runaway multi-turn simulations, internal reasoning leaks, and repetitive question loops."""
    if not text:
        return ""
    cut = re.split(r"(?:\bUser (?:gave|hasn't|has not|says|asked|replied)|\b(?:User|Customer|Assistant|Agent)\s*:)", text, flags=re.I)[0]
    sentences = re.split(r"(?<=[.?!])\s*(?=[A-Z0-9]|$)", cut.strip())
    seen = set()
    kept = []
    for s in sentences:
        norm = re.sub(r"\W+", "", s).lower()
        if norm and norm not in seen:
            seen.add(norm)
            kept.append(s.strip())
        if len(kept) >= 2:
            break
    return " ".join(kept) if kept else cut.strip()


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


FAILED_ERRORS = frozenset({ToolError.SYSTEM_UNAVAILABLE, ToolError.BAD_ARGUMENTS, ToolError.UNKNOWN_TOOL})


def op_outcome(result: dict) -> OpOutcome:
    """OK when the tool did its work; FAILED when the system or the call broke; DECLINED when a rule refused it."""
    error = result.get("error")
    if error is None:
        return OpOutcome.OK
    code = str(error)
    if code in FAILED_ERRORS or (code.startswith(HTTP_ERROR_PREFIX) and code[len(HTTP_ERROR_PREFIX):].startswith("5")):
        return OpOutcome.FAILED
    return OpOutcome.DECLINED


def _trim(result: dict) -> dict:
    raw = json.dumps(result)
    return result if len(raw) <= RETRIEVED_LIMIT else {"truncated": raw[:RETRIEVED_LIMIT]}


def window(messages: list[dict], turns: int = HISTORY_TURNS, state: str = "") -> list[dict]:
    """The system prompt plus the last `turns` caller turns, cut only at a caller message so tool calls keep their results.
    Tool results before the current caller turn are shortened: the agent already used them, and they cost tokens.
    `state` is added to the system prompt: facts about the call that must outlive the window, such as verification."""
    system = {**messages[0], "content": f"{messages[0]['content']}\n{state}"} if state else messages[0]
    users = [i for i, m in enumerate(messages) if m["role"] == "user"]
    if not users:
        return [system, *messages[1:]]
    start = users[-turns] if len(users) > turns else 1
    current = users[-1]
    out = [system]
    for i, m in enumerate(messages[start:], start):
        if i < current and m["role"] == "tool" and len(m.get("content") or "") > OLD_TOOL_RESULT_CHARS:
            m = {**m, "content": m["content"][:OLD_TOOL_RESULT_CHARS] + "…(shortened)"}
        out.append(m)
    return out


TEXT_TOOL_NAME = re.compile(r'^\s*\{.*?"name\\?"\s*:\s*\\?"(\w+)', re.S)


def recover_text_tool_call(content: str | None) -> dict | None:
    """Small local models sometimes write a tool call as reply text ('{"name": "get_loans", "parameters": {...}}').
    Turn that into the tool call it meant, so it is run and never spoken; None when the text is a normal reply."""
    m = TEXT_TOOL_NAME.match(content or "")
    if not m or m.group(1) not in SupportTool.__members__.values():
        return None
    raw = (content or "").replace("\\n", "").replace("\\", "").replace("\n", "")
    args: dict = {}
    try:
        body = json.loads(raw)
        args = body.get("parameters") or body.get("arguments") or {}
    except ValueError:
        pass
    return {"id": f"text-{abs(hash(raw)) % 10**8}", "type": "function",
            "function": {"name": m.group(1), "arguments": json.dumps(args if isinstance(args, dict) else {})}}


def _misunderstood(turn: SupportTurn) -> bool:
    """A turn counts towards the misunderstanding hand-over only when the model classifier itself found nothing but UNCLEAR
    and the agent reached no bank tool. The rule fallback (used when the model classifier is down) labels short
    confirmations such as 'yes please' or 'the first one' UNCLEAR, and a turn the agent answered with a tool was understood."""
    return turn.intents == [Intent.UNCLEAR] and turn.intent_source == IntentSource.LLM and not turn.tool_calls


def outcome_for(refs: list[str]) -> Outcome:
    for prefix, outcome in OUTCOME_BY_PREFIX:
        if any(r.startswith(prefix) for r in refs):
            return outcome
    return Outcome.RESOLVED


class SupportBrain:
    def __init__(self, llm: ChatClient, sim: SimulatorClient, calls: SupportCallsApi | None, call: CallSession,
                 classify: Classifier | None = None, lessons: list[str] | None = None,
                 languages: tuple[SpeechLanguage, ...] = (SpeechLanguage.ENGLISH,), translator: Translator | None = None):
        self._llm, self._sim, self._calls, self.call, self._classify = llm, sim, calls, call, classify
        self._translator = translator
        self._messages: list[dict] = [{"role": "system", "content": support_prompt(lessons, languages)}, {"role": "assistant", "content": GREETING}]
        self.rating: int | None = None
        self._lock = asyncio.Lock()
        self._seq = 0
        self._pending: set[asyncio.Task] = set()
        self.ended = False

    async def open(self) -> None:
        await self._record(TurnRole.AGENT, GREETING, {MetaKey.GREETING: True})

    async def reply(self, user_text: str, audio: bytes | None = None, audio_suffix: str = ".wav") -> SupportTurn:
        async with self._lock:
            user_text = normalise_spoken_digits(user_text)
            self._hear_identity(user_text)
            history = [m for m in self._messages if m["role"] in {"user", "assistant"} and m.get("content")][-4:]
            intents = asyncio.create_task(self._intents(user_text, history))
            customer_seq = await self._record(TurnRole.CUSTOMER, user_text, self._verification())
            self._translate_later(customer_seq, user_text)
            has_audio = self._keep_audio(customer_seq, audio, audio_suffix)
            self._messages.append({"role": "user", "content": user_text})
            self.call.last_caller_text = user_text  # a complaint raised this turn keeps the caller's own words
            locked_before = self.call.locked
            turn = await self._loop()
            turn.intents, turn.intent_source = await intents  # usually done long before the reply; the backstops need them
            self.call.unclear_streak = self.call.unclear_streak + 1 if _misunderstood(turn) else 0
            acted = await self._act_on_fraud_if_missed(user_text, turn)
            if await self._escalate_if_stuck(turn, locked_before=locked_before) or acted:
                again = await self._loop()  # the reply the caller hears now carries the references raised, or the failure
                turn.text, turn.tool_calls, turn.model, turn.ended = again.text, turn.tool_calls + again.tool_calls, again.model or turn.model, self.ended
            self._messages.append({"role": "assistant", "content": turn.text})  # after the backstops: a replaced reply leaves no trace
            await self._route_if_missed(user_text, turn)
            turn.verified, turn.refs = self.call.verified, list(self.call.refs)
            turn.locked, turn.verify_failures = self.call.locked, self.call.verify_failures
            agent_seq = await self._record(TurnRole.AGENT, turn.text,
                                           {MetaKey.TOOL_TRACE: [{"name": t.name, "args": t.args, "result_summary": summarise(t.result),
                                                                  "outcome": op_outcome(t.result)}
                                                                 for t in turn.tool_calls],
                                            MetaKey.RETRIEVED: {t.name: _trim(t.result) for t in turn.tool_calls},
                                            MetaKey.REFS: turn.refs, MetaKey.VERIFIED: self.call.verified})
            self._translate_later(agent_seq, turn.text)
            await self._patch(customer_seq, {**self._verification(), MetaKey.INTENTS: turn.intents, MetaKey.INTENT_SOURCE: turn.intent_source,
                                             **({MetaKey.AUDIO: True} if has_audio else {})})
            return turn

    def _hear_identity(self, text: str) -> set[VerifyField]:
        """Keeps the mobile number and date of birth the caller said, so verify_customer uses them rather than the model's
        copy. A new value replaces the old (latest wins); a turn without one leaves it; a wrong-length number is remembered
        so the agent can say how many digits it heard. Only numbers this code could not read let the model fill a field.
        Returns the fields this text filled."""
        call = self.call
        filled: set[VerifyField] = set()
        if mobile := extract_mobile(text):
            call.heard_mobile, call.heard_digits = mobile, None
            filled.add(VerifyField.MOBILE)
        elif (run := digit_run(text)) and is_mobile_attempt(run):
            call.heard_digits = run
        if dob := extract_dob(text, call.today):
            call.heard_dob = dob
            filled.add(VerifyField.DOB)
        call.model_may_fill.update(unexplained_fields(text))  # only the detail the unread numbers may hold
        return filled

    async def apply_correction(self, seq: int, text: str) -> dict[str, bool]:
        """A reviewer corrected what the caller said on turn `seq` (the panel's transcript correction, already on the record):
        the identity details are read from the corrected words as if the caller had just said them, so a corrected mobile
        number or date of birth replaces what was misheard (and refills a field forgotten after a bank mismatch), and the
        model is told to use the correction. Nothing is spoken, the bank is not called and no verification attempt is spent.
        Returns which identity fields the correction filled. Removing the correction later does not un-hear it."""
        async with self._lock:  # waits for a reply in flight on purpose: the correction must land between turns, never inside one
            # The same normalisation a caller turn gets: references at the speech stage (keep_transcript / transcribe_file),
            # spoken digits again in reply(); a typed 'TXN 88213' is then a reference, not unexplained digits for the model to fill.
            text = normalise_spoken_digits(normalise_refs(text))
            filled = self._hear_identity(text)
            self._messages.append({"role": "user", "content": CORRECTION_NOTE.format(text=text)})
            logger.info(f"call {self.call.call_id}: reviewer corrected turn {seq}; filled {sorted(str(f) for f in filled)}")
            return {HEARD_KEY[f]: f in filled for f in VerifyField}

    def mark_unheard(self) -> None:
        """The caller interrupted before hearing the last reply: keep it in context, but say it was never heard."""
        for m in reversed(self._messages):
            if m["role"] == "assistant" and m.get("content") and not m.get("tool_calls"):
                m["content"] = f"(Not heard: the caller interrupted before this was spoken.) {m['content']}"
                return

    async def no_speech(self, reason: str) -> None:
        """A customer turn with nothing to answer (silence, or noise the model turned into words): recorded, not replied to."""
        async with self._lock:
            await self._record(TurnRole.CUSTOMER, "", {**self._verification(), MetaKey.NO_SPEECH: True, MetaKey.REASON: reason, MetaKey.INTENTS: []})

    async def _act_on_fraud_if_missed(self, user_text: str, turn: SupportTurn) -> bool:
        """Backstop for 'unauthorised transaction: complaint plus escalation at once': a verified caller reporting a payment
        they did not make gets both, even when the model only offered options. Runs the missing tools; True if it ran any."""
        if not self.call.verified or not UNAUTHORISED.search(user_text):
            return False
        done = {t.name for t in turn.tool_calls if "error" not in t.result}
        has = lambda prefix: any(r.startswith(prefix) for r in self.call.refs)
        needed = []
        if SupportTool.REGISTER_COMPLAINT not in done and not has(RefPrefix.COMPLAINT):
            needed.append((SupportTool.REGISTER_COMPLAINT, {"category": ComplaintCategory.UNAUTHORISED_TRANSACTION, "description": user_text,
                                                            "severity": Severity.HIGH}))
        if SupportTool.ESCALATE_TO_HUMAN not in done and not has(RefPrefix.ESCALATION):
            needed.append((SupportTool.ESCALATE_TO_HUMAN, {"trigger": EscalationTrigger.SENSITIVE, "summary": user_text,
                                                           "reason": "The caller reports a transaction they did not authorise"}))
        return await self._run_backstop(turn, needed)

    async def _escalate_if_stuck(self, turn: SupportTurn, *, locked_before: bool = False) -> bool:
        """Backstop for 'escalate on repeated authentication failures' and 'repeated misunderstanding of customer intent':
        one hand-over when verification locked this turn, or when the caller has not been understood for
        UNCLEAR_BEFORE_ESCALATION turns in a row. Runs after the intents are known; True if it ran."""
        if any(r.startswith(RefPrefix.ESCALATION) for r in self.call.refs) or any(t.name == SupportTool.ESCALATE_TO_HUMAN for t in turn.tool_calls):
            return False  # already with a person, or the model tried this turn and the caller will hear how that went
        if self.call.locked and not locked_before:
            # The bank may lock on the first attempt (the caller was locked on an earlier call), so the count is stated only when
            # the failures happened here; a record must never carry a number that did not happen.
            summary = (f"Verification locked after {self.call.verify_failures} failed attempts" if self.call.verify_failures
                       else "Customer verification is locked; no attempt could be accepted on this call")
            args = {"trigger": EscalationTrigger.AUTH_LOCKED, "reason": "The caller could not be verified and verification is locked",
                    "summary": summary}
        elif self.call.unclear_streak >= UNCLEAR_BEFORE_ESCALATION:
            args = {"trigger": EscalationTrigger.REPEATED_MISUNDERSTANDING, "reason": "The agent kept failing to understand the caller",
                    "summary": f"Request not understood after {self.call.unclear_streak} turns; last words: {self.call.last_caller_text}"}
            self.call.unclear_streak = 0  # one attempt per run of misunderstandings; a failed hand-over is not retried every turn
        else:
            return False
        return await self._run_backstop(turn, [(SupportTool.ESCALATE_TO_HUMAN, args)])

    async def _run_backstop(self, turn: SupportTurn, needed: list[tuple[SupportTool, dict]]) -> bool:
        """Runs tools the model should have called, as if it had: the calls and their results join the history, so the
        next `_loop()` speaks from them. True if any ran."""
        if not needed:
            return False
        calls = [{"id": f"backstop-{len(self._messages)}-{i}", "type": "function", "function": {"name": str(n), "arguments": json.dumps(a)}}
                 for i, (n, a) in enumerate(needed)]
        self._messages.append({"role": "assistant", "content": None, "tool_calls": calls})
        for c in calls:
            trace = await self._run(c)
            turn.tool_calls.append(trace)
            self._messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(trace.result)})
        return True

    async def _route_if_missed(self, user_text: str, turn: SupportTurn) -> None:
        """Backstop for the acceptance rule 'route unsupported requests': if the caller's request was detected as
        unsupported and the model declined without routing it (or escalating), route it here."""
        if str(Intent.UNSUPPORTED) not in turn.intents:
            return
        if any(t.name in (SupportTool.ROUTE_UNSUPPORTED, SupportTool.ESCALATE_TO_HUMAN) for t in turn.tool_calls):
            return
        args = {"query_text": user_text, "reason": "Outside the desk's services (detected as unsupported)"}
        result = await run_support_tool(self._sim, self.call, SupportTool.ROUTE_UNSUPPORTED, args)
        turn.tool_calls.append(ToolTrace(SupportTool.ROUTE_UNSUPPORTED, args, result))

    async def finish(self, outcome: str | None = None) -> str:
        outcome = outcome or outcome_for(self.call.refs)
        if self._pending:  # give in-flight translations a moment; whatever is still running patches the turn after the end
            await asyncio.wait(set(self._pending), timeout=TRANSLATE_GRACE_SECS)
        if self._calls:
            try:
                await self._calls.end(self.call.call_id, outcome)
            except ApiUnavailable as e:
                logger.warning(f"call end not recorded: {e}")
        return outcome

    def _call_state(self) -> str:
        if not self.call.verified:
            return ""
        who = self.call.customer or {}
        # N1: name only, never the CUST- id: the prompt forbids saying it, and the tools read customer_ref from call.customer.
        return (f"CALL STATE: the caller is already verified as {who.get('first_name', 'the customer')} "
                "for the rest of this call. Do not ask for their mobile "
                "number or date of birth again and do not call verify_customer again; use the personal tools directly.")

    async def _loop(self) -> SupportTurn:
        traces: list[ToolTrace] = []
        model = None
        for _ in range(MAX_TOOL_ROUNDS):
            msg = await self._llm.complete(window(self._messages, state=self._call_state()), SUPPORT_TOOL_SCHEMAS)
            model = msg.get("model", model)
            calls = msg.get("tool_calls") or []
            if not calls and (recovered := recover_text_tool_call(msg.get("content"))):
                calls, msg = [recovered], {**msg, "content": None}
            if not calls:
                return SupportTurn(_clean_reply(msg.get("content") or ""), traces, model=model, ended=self.ended)
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
            return ToolTrace(name, {}, {"error": ToolError.BAD_ARGUMENTS, "detail": f"invalid JSON: {e}"[:200]})
        if name == SupportTool.END_CALL:
            self.ended = True
        if name == SupportTool.RECORD_RATING:
            return ToolTrace(name, args, await self._record_rating(args))
        return ToolTrace(name, args, await run_support_tool(self._sim, self.call, name, args))

    def _keep_audio(self, seq: int, audio: bytes | None, suffix: str) -> bool:
        if not audio:
            return False
        try:
            recordings.save(self.call.call_id, seq, audio, suffix)
            return True
        except (OSError, ValueError) as e:
            logger.warning(f"turn audio not kept: {e}")
            return False

    async def _record_rating(self, args: dict) -> dict:
        try:
            score = int(args.get("score"))
        except (TypeError, ValueError):
            return {"error": ToolError.BAD_ARGUMENTS, "note": "The score must be a whole number from 1 to 5."}
        if not 1 <= score <= 5:
            return {"error": ToolError.BAD_ARGUMENTS, "note": "The score must be from 1 to 5; ask again or skip it."}
        comment = (str(args.get("comment") or "").strip() or None)
        self.rating = score
        if self._calls:
            try:
                await self._calls.rating(self.call.call_id, score, comment)
            except ApiUnavailable as e:
                logger.warning(f"rating not recorded: {e}")
                return {"recorded": False, "note": "Thank them anyway; the rating could not be saved."}
        return {"recorded": True, "score": score}

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
        return {MetaKey.VERIFIED: self.call.verified, MetaKey.VERIFY_FAILURES: self.call.verify_failures, MetaKey.LOCKED: self.call.locked}

    async def _record(self, role: TurnRole, text: str, meta: dict) -> int:
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

    def _translate_later(self, seq: int, text: str) -> None:
        """A Kannada or Hindi turn gets its English put on the record in the background; the reply never waits for it.
        English turns, no translator, or no call records: nothing to do."""
        if self._translator is None or not self._calls:
            return
        language = script_language(text)
        if language not in TRANSLATED_SCRIPTS:
            return
        task = asyncio.create_task(self._translate(seq, text, language))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _translate(self, seq: int, text: str, language: SpeechLanguage) -> None:
        try:
            english = await self._translator(text)
        except Exception as e:  # advisory: a failed translation leaves the turn as it was
            logger.warning(f"translation failed: {type(e).__name__}")
            return
        if not english:
            return
        await self._patch(seq, {MetaKey.TEXT_EN: english, MetaKey.LANGUAGE: language})
