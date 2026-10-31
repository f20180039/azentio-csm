import asyncio
import json
import os
import time
from uuid import UUID
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCPatchRequest

from . import phone
from .api_client import ApiUnavailable, RenewalsApi, SupportCallsApi
from .brain import CallBrain, ChatClient
from .config import Settings, load_settings
from .llm_chain import ChainChatClient, ChainState, LLMUnavailable
from .prompt import system_prompt
from .simulator_client import SimulatorClient
from .speech import CallLanguage, voice_for
from .support_brain import SupportBrain, SupportTurn, op_outcome
from .support_prompt import GREETING
from .support_tools import CallSession
from .translate import to_english
from .vocab import Channel, Outcome, Route


class State:
    def __init__(self) -> None:
        self.api: RenewalsApi | None = None
        self.llm: ChatClient | None = None
        self.chain: ChainState | None = None
        self.brains: dict[str, CallBrain] = {}
        self.support: dict[str, SupportBrain] = {}
        self.sim: SimulatorClient | None = None
        self.support_calls: SupportCallsApi | None = None
        self.stt_transport: httpx.AsyncBaseTransport | None = None
        self._lessons: tuple[float, list[str]] | None = None
        self.webrtc = None
        self.live_calls: dict[str, str | None] = {}
        self.phone_pending: dict[str, tuple[str, float]] = {}
        self.twilio_transport: httpx.AsyncBaseTransport | None = None
        self.tunnel_transport: httpx.AsyncBaseTransport | None = None
        self._settings: Settings | None = None

    def settings(self) -> Settings:
        if self._settings is None:
            env_file = Path(__file__).resolve().parents[3] / ".env"
            if not env_file.exists():
                env_file = Path(__file__).resolve().parents[2] / ".env"
            self._settings = load_settings(env_file if env_file.exists() else None)
        return self._settings

    def get_api(self) -> RenewalsApi:
        if self.api is None:
            self.api = RenewalsApi(self.settings())
        return self.api

    def get_sim(self) -> SimulatorClient:
        if self.sim is None:
            self.sim = SimulatorClient(self.settings())
        return self.sim

    def get_support_calls(self) -> SupportCallsApi:
        if self.support_calls is None:
            self.support_calls = SupportCallsApi(self.settings())
        return self.support_calls

    def classifier(self):
        try:
            from .intents import classify
        except ImportError:
            return None
        s = self.settings()

        async def run(text: str, history: list[dict]):
            return await classify(text, history, api_key=s.groq_api_key, model=getattr(s, "intent_model", "openai/gpt-oss-20b"))
        return run

    def translator(self):
        """English for Kannada and Hindi turns on the record; None without a Groq key, so no turn is ever sent anywhere."""
        s = self.settings()
        if not s.groq_api_key:
            return None

        async def run(text: str) -> str | None:
            return await to_english(text, api_key=s.groq_api_key, model=s.translate_model)
        return run

    async def lessons(self) -> list[str]:
        """Supervisor-approved lessons for the support prompt, cached for a minute; none if the API is unreachable."""
        now = time.monotonic()
        if self._lessons is None or now - self._lessons[0] > LESSONS_TTL_SECS:
            try:
                self._lessons = (now, await self.get_support_calls().active_lessons())
            except ApiUnavailable:
                self._lessons = (now, self._lessons[1] if self._lessons else [])
        return self._lessons[1]

    async def new_support_brain(self, channel: Channel, call_id: str | None = None) -> SupportBrain:
        """Starts a support call in Spring (or continues a known one) and opens its brain."""
        if call_id and call_id in self.support:
            return self.support[call_id]
        try:
            call_id = call_id or await self.get_support_calls().start(channel)
        except ApiUnavailable as e:
            raise HTTPException(502, "call records API unavailable") from e
        brain = SupportBrain(self.get_llm(), self.get_sim(), self.get_support_calls(),
                             CallSession(call_id, helpline=self.settings().helpline_number), self.classifier(), await self.lessons(),
                             self.settings().voice_languages, translator=self.translator())
        await brain.open()
        self.support[call_id] = brain
        return brain

    def get_chain(self) -> ChainState:
        if self.chain is None:
            self.chain = ChainState(self.settings().llm_chain)
        return self.chain

    def get_llm(self) -> ChatClient:
        if self.llm is None:
            self.llm = ChainChatClient(self.settings().llm_chain, state=self.get_chain())
        return self.llm


state = State()
EVAL_LATEST = Path(__file__).resolve().parents[1] / "eval" / "out" / "latest.json"
app = FastAPI(title="Renewal Desk voice")
TUNNEL_HEADERS = (b"cf-connecting-ip", b"cf-ray", b"x-forwarded-for", b"forwarded")
PUBLIC_PATHS = (Route.TWILIO_WS, Route.TWILIO_TWIML, Route.HEALTH,
                Route.TWILIO_SUPPORT_INCOMING, Route.TWILIO_SUPPORT_TWIML, Route.TWILIO_SUPPORT_WS)


class LocalOnly:
    """A request that came through a proxy or tunnel may reach only Twilio's TwiML fetch, its media stream and /health."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and scope["path"] not in PUBLIC_PATHS:
            if any(name.lower() in TUNNEL_HEADERS for name, _ in scope.get("headers", [])):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                body = b'{"detail":"LOCAL_ONLY"}'
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.add_middleware(LocalOnly)


class TextCallIn(BaseModel):
    callId: UUID


class TextTurnIn(BaseModel):
    callId: UUID
    text: str


@app.get(Route.HEALTH)
async def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/llm/status")
async def llm_status() -> dict:
    return state.get_chain().status()


@app.get("/v1/eval/latest")
async def eval_latest() -> dict:
    if not EVAL_LATEST.exists():
        raise HTTPException(404, "no simulated test run yet")
    return json.loads(EVAL_LATEST.read_text())


@app.post("/v1/text-call")
async def text_call(body: TextCallIn) -> dict:
    call_id = str(body.callId)
    existing = state.brains.get(call_id)
    if existing is not None:
        return {"greeting": existing.greeting}
    api = state.get_api()
    try:
        call = await api.call(call_id)
    except ApiUnavailable as e:
        raise HTTPException(502, "renewals API unavailable") from e
    if call.get("error") or not call.get("greeting"):
        raise HTTPException(404, "unknown call")
    brain = CallBrain(state.get_llm(), api, call_id, system_prompt(call["greeting"]))
    await brain.say(call["greeting"])
    brain.greeting = call["greeting"]
    state.brains[call_id] = brain
    return {"greeting": call["greeting"]}


@app.post("/v1/text-turn")
async def text_turn(body: TextTurnIn) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "text must not be blank")
    brain = state.brains.get(str(body.callId))
    if brain is None:
        raise HTTPException(404, "unknown call")
    try:
        turn = await brain.reply(body.text)
    except ApiUnavailable as e:
        raise HTTPException(502, "renewals API unavailable") from e
    except LLMUnavailable as e:
        if e.daily:
            raise HTTPException(429, "LLM_DAILY_LIMIT") from e
        raise HTTPException(502, "language model unavailable") from e
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429 and "per day" in e.response.text:
            raise HTTPException(429, "LLM_DAILY_LIMIT") from e
        raise HTTPException(502, "language model unavailable") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, "language model unavailable") from e
    return {
        "reply": turn.text,
        "toolCalls": [{"name": t.name, "args": t.args, "result": t.result} for t in turn.tool_calls],
        "model": turn.model,
    }


def turn_json(turn: SupportTurn) -> dict:
    return {"reply_text": turn.text, "intents": turn.intents, "intent_source": turn.intent_source, "verified": turn.verified,
            "locked": turn.locked, "verify_failures": turn.verify_failures,
            "refs": turn.refs, "ended": turn.ended, "model": turn.model, "retrieved": turn.retrieved(),
            "tool_trace": [{"name": t.name, "args": t.args, "result": t.result, "outcome": op_outcome(t.result)}
                           for t in turn.tool_calls]}


async def support_reply(brain: SupportBrain, text: str, audio: bytes | None = None, audio_suffix: str = ".wav") -> SupportTurn:
    try:
        return await brain.reply(text, audio=audio, audio_suffix=audio_suffix)
    except LLMUnavailable as e:
        raise HTTPException(429 if e.daily else 502, "LLM_DAILY_LIMIT" if e.daily else "language model unavailable") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, "language model unavailable") from e


class SupportTextTurnIn(BaseModel):
    call_id: UUID
    text: str


class SupportEndIn(BaseModel):
    call_id: UUID
    outcome: Outcome | None = None  # validated at the boundary: an unknown outcome is a 422


@app.post(Route.SUPPORT_TEXT_CALL)
async def support_text_call() -> dict:
    brain = await state.new_support_brain(Channel.TEXT)
    return {"call_id": brain.call.call_id, "greeting": GREETING}


@app.post(Route.SUPPORT_TEXT_TURN)
async def support_text_turn(body: SupportTextTurnIn) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "text must not be blank")
    brain = state.support.get(str(body.call_id))
    if brain is None:
        raise HTTPException(404, "unknown call")
    return turn_json(await support_reply(brain, body.text.strip()))


LESSONS_TTL_SECS = 60
MAX_SIM_FILES = 20
MAX_SIM_BYTES = 10 * 1024 * 1024


async def spoken_reply(text: str, call_language: CallLanguage | None = None) -> str | None:
    """The reply as base64 MP3 in the same voice as live calls; None if the read-aloud service is unreachable."""
    import base64

    import edge_tts
    try:
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, voice_for(text, state.settings().tts_voice, call_language)).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return base64.b64encode(bytes(audio)).decode() if audio else None
    except Exception as e:
        logger.warning(f"reply audio not generated: {e!r}")
        return None


@app.post(Route.SIM_AUDIO)
async def sim_audio(files: list[UploadFile] = File(...), call_id: str | None = Form(None), speak: bool = Form(True)) -> dict:
    """Recorded-audio simulation: one file per customer turn, in order, through the same speech front end and brain as live calls."""
    from .speech_file import transcribe_file

    if not files or len(files) > MAX_SIM_FILES:
        raise HTTPException(400, f"send 1 to {MAX_SIM_FILES} audio files")
    if call_id is not None:
        try:
            call_id = str(UUID(call_id))
        except ValueError:
            raise HTTPException(400, "call_id must be a UUID") from None
        if call_id not in state.support:
            raise HTTPException(404, "unknown call")
    brain = await state.new_support_brain(Channel.SIM_AUDIO, call_id)
    s = state.settings()
    language = CallLanguage(s.voice_languages)
    turns = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_SIM_BYTES:
            raise HTTPException(413, f"{f.filename} is larger than 10 MB")
        started = time.monotonic()
        try:
            heard = await transcribe_file(data, api_key=s.groq_api_key, model=s.stt_model, transport=state.stt_transport,
                                         call_language=language)
        except (httpx.HTTPError, ValueError, OSError) as e:  # an unreadable file, or speech-to-text down
            raise HTTPException(422 if isinstance(e, (ValueError, OSError)) else 502, f"{f.filename}: could not transcribe ({type(e).__name__})") from e
        row = {"file": f.filename, "transcript": heard.text, "no_speech": heard.text is None, "speech_secs": round(heard.speech_secs, 2),
               "upload_bytes": heard.upload_bytes}
        if heard.text is None:
            await brain.no_speech(heard.reason)
            turns.append({**row, "reason": heard.reason, "intents": [], "verified": brain.call.verified, "locked": brain.call.locked, "tool_trace": [], "retrieved": {},
                          "reply_text": None, "reply_audio_b64": None, "latency_ms": round((time.monotonic() - started) * 1000)})
            continue
        turn = await support_reply(brain, heard.text, audio=data, audio_suffix=Path(f.filename or "").suffix or ".wav")
        audio = await spoken_reply(turn.text, language) if speak and turn.text else None
        turns.append({**row, **turn_json(turn), "reply_audio_b64": audio, "latency_ms": round((time.monotonic() - started) * 1000)})
        if turn.ended:
            break
    outcome = await brain.finish() if brain.ended else None
    if outcome:
        state.support.pop(brain.call.call_id, None)
    return {"call_id": brain.call.call_id, "turns": turns, "ended": brain.ended, "outcome": outcome}


@app.get(Route.TURN_AUDIO)
async def turn_audio(call_id: str, seq: int):
    """What the caller said on that turn, for playback beside the transcript (local only, like the other support routes)."""
    from fastapi.responses import FileResponse

    from . import recordings
    path = recordings.find(call_id, seq)
    if path is None:
        raise HTTPException(404, "no audio for that turn")
    return FileResponse(path, media_type=recordings.MEDIA_TYPES.get(path.suffix, "application/octet-stream"))


class SupportPauseIn(BaseModel):
    paused: bool


@app.post(Route.SUPPORT_PAUSE)
async def support_pause(call_id: UUID, body: SupportPauseIn) -> dict:
    """Pause or resume a live call for side talk: while paused the agent ignores the caller and does not hang up on silence."""
    from .support_pipeline import LIVE

    responder = LIVE.get(str(call_id))
    if responder is None:
        raise HTTPException(404, "no live call")
    await responder.set_paused(body.paused)
    return {"paused": responder.paused}


@app.post(Route.SUPPORT_END)
async def support_end(body: SupportEndIn) -> dict:
    brain = state.support.pop(str(body.call_id), None)
    if brain is None:
        raise HTTPException(404, "unknown call")
    return {"outcome": await brain.finish(body.outcome)}


class OfferIn(BaseModel):
    sdp: str
    type: str
    pc_id: str | None = None
    restart_pc: bool | None = None
    requestData: dict | None = None


@app.post(Route.API_OFFER)
async def offer(body: OfferIn, background_tasks: BackgroundTasks) -> dict:
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest, SmallWebRTCRequestHandler
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from .pipeline import build_pipeline

    call_id = (body.requestData or {}).get("callId")
    if not body.pc_id and not call_id:
        raise HTTPException(400, "requestData.callId is required")
    if call_id is not None:
        try:
            call_id = str(UUID(str(call_id)))
        except ValueError:
            raise HTTPException(400, "requestData.callId must be a UUID") from None
    renegotiation = body.pc_id is not None and body.pc_id in state.live_calls.values()
    if not renegotiation:
        if call_id in state.live_calls:
            raise HTTPException(409, "CALL_IN_PROGRESS")
        state.live_calls[call_id] = None
    if state.webrtc is None:
        state.webrtc = SmallWebRTCRequestHandler()
    failure: list[Exception] = []

    async def run(task) -> None:
        try:
            await PipelineRunner(handle_sigint=False).run(task)
        finally:
            state.live_calls.pop(call_id, None)

    async def on_connection(connection) -> None:
        transport = SmallWebRTCTransport(
            params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
            webrtc_connection=connection,
        )
        try:
            task = await build_pipeline(state.settings(), call_id, transport, chain=state.get_chain())
        except Exception as e:
            failure.append(e)
            await connection.disconnect()
            return
        background_tasks.add_task(run, task)

    request = SmallWebRTCRequest(
        sdp=body.sdp, type=body.type, pc_id=body.pc_id, restart_pc=body.restart_pc, request_data=body.requestData
    )
    try:
        answer = await state.webrtc.handle_web_request(request, on_connection)
    except Exception:
        if not renegotiation:
            state.live_calls.pop(call_id, None)
        raise
    if failure:
        state.live_calls.pop(call_id, None)
        logger.warning(f"voice call {call_id} not started: {failure[0]!r}")
        if isinstance(failure[0], LookupError):
            raise HTTPException(404, "unknown call")
        raise HTTPException(502, "voice call could not start")
    if not renegotiation:
        state.live_calls[call_id] = answer["pc_id"]
    return answer


@app.post(Route.SUPPORT_OFFER)
async def support_offer(body: OfferIn, background_tasks: BackgroundTasks) -> dict:
    """WebRTC mic call to the front desk. A first offer starts a support call; a renegotiation (pc_id) reuses it."""
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest, SmallWebRTCRequestHandler
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    from .support_pipeline import build_support_pipeline

    renegotiation = body.pc_id is not None and body.pc_id in state.live_calls.values()
    brain = None if renegotiation else await state.new_support_brain(Channel.VOICE)
    call_id = brain.call.call_id if brain else next(c for c, pc in state.live_calls.items() if pc == body.pc_id)
    if not renegotiation:
        state.live_calls[call_id] = None
    if state.webrtc is None:
        state.webrtc = SmallWebRTCRequestHandler()

    async def run(task) -> None:
        from .support_pipeline import LIVE

        try:
            await PipelineRunner(handle_sigint=False).run(task)
        finally:
            state.live_calls.pop(call_id, None)
            state.support.pop(call_id, None)
            LIVE.pop(call_id, None)

    async def on_connection(connection) -> None:
        transport = SmallWebRTCTransport(params=TransportParams(audio_in_enabled=True, audio_out_enabled=True), webrtc_connection=connection)
        background_tasks.add_task(run, build_support_pipeline(state.settings(), brain, transport))

    request = SmallWebRTCRequest(sdp=body.sdp, type=body.type, pc_id=body.pc_id, restart_pc=body.restart_pc, request_data=body.requestData)
    try:
        answer = await state.webrtc.handle_web_request(request, on_connection)
    except Exception:
        if not renegotiation:
            state.live_calls.pop(call_id, None)
        raise
    if not renegotiation:
        state.live_calls[call_id] = answer["pc_id"]
    return {**answer, "call_id": call_id}


@app.patch(Route.SUPPORT_OFFER)
async def support_ice_candidate(body: SmallWebRTCPatchRequest) -> dict:
    return await ice_candidate(body)


@app.patch(Route.API_OFFER)
async def ice_candidate(body: SmallWebRTCPatchRequest) -> dict:
    """Trickled ICE candidates from the browser transport, forwarded to Pipecat's own handler."""
    if state.webrtc is None:
        raise HTTPException(404, "Peer connection not found")
    await state.webrtc.handle_patch_request(body)
    return {"status": "success"}


class PhoneNumberIn(BaseModel):
    to: str | None = None
    numberId: str | None = None


class PhoneCallIn(PhoneNumberIn):
    callId: UUID


def _allowed_number(body: PhoneNumberIn, s: Settings) -> str:
    """The allow-listed number to dial, by id from /v1/phone/allowed or spelled out; refuses anything else."""
    allowed = s.twilio_allowed_to
    if body.numberId is not None and not (body.numberId.isascii() and body.numberId.isdecimal()):
        raise HTTPException(400, "numberId must be a number id from /v1/phone/allowed")
    if not allowed:
        raise HTTPException(503, "PHONE_NOT_CONFIGURED")
    if body.numberId is not None:
        to = allowed[int(body.numberId)] if int(body.numberId) < len(allowed) else None
    else:
        to = (body.to or "").replace(" ", "")
        to = to if to in allowed else None
    if to is None:
        raise HTTPException(403, "NUMBER_NOT_ALLOWED")
    if not phone.configured(s):
        raise HTTPException(503, "PHONE_NOT_CONFIGURED")
    return to


def _pending_sid(call_id: str) -> str | None:
    entry = state.phone_pending.get(call_id)
    if entry is None:
        return None
    if time.monotonic() - entry[1] > phone.PENDING_TTL_SECS:
        state.phone_pending.pop(call_id, None)
        return None
    return entry[0]


@app.get(Route.PHONE_ALLOWED)
async def phone_allowed() -> dict:
    s = state.settings()
    if not phone.configured(s):
        return {"configured": False, "numbers": []}
    return {"configured": True, "numbers": [{"id": str(i), "masked": phone.mask(n)} for i, n in enumerate(s.twilio_allowed_to)]}


@app.post(Route.PHONE_CALL)
async def phone_call(body: PhoneCallIn) -> dict:
    s = state.settings()
    call_id = str(body.callId)
    to = _allowed_number(body, s)
    if call_id in state.live_calls or _pending_sid(call_id) is not None:
        raise HTTPException(409, "CALL_IN_PROGRESS")
    if _phone_busy():
        raise HTTPException(409, "PHONE_BUSY")
    state.phone_pending[call_id] = ("", time.monotonic())
    try:
        call = await state.get_api().call(call_id)
    except ApiUnavailable as e:
        state.phone_pending.pop(call_id, None)
        raise HTTPException(502, "renewals API unavailable") from e
    if call.get("error") or not call.get("greeting"):
        state.phone_pending.pop(call_id, None)
        raise HTTPException(404, "unknown call")
    if call.get("outcome"):
        state.phone_pending.pop(call_id, None)
        raise HTTPException(409, "CALL_ENDED")
    if not await phone.tunnel_up(s.public_base_url, transport=state.tunnel_transport):
        state.phone_pending.pop(call_id, None)
        logger.warning(f"phone call {call_id} not placed: PUBLIC_BASE_URL/health did not answer")
        raise HTTPException(503, "TUNNEL_DOWN")
    try:
        sid = await phone.dial(s, call_id, to, transport=state.twilio_transport)
    except phone.DialError as e:
        state.phone_pending.pop(call_id, None)
        detail = phone.mask_numbers(str(e))
        logger.warning(f"phone call {call_id} not placed: {detail}")
        raise HTTPException(502, detail) from None
    state.phone_pending[call_id] = (sid, time.monotonic())
    logger.info(f"phone call {call_id} dialled as {sid} to {phone.mask(to)}")
    return {"status": "dialling"}


@app.post(Route.TWILIO_TWIML)
async def twilio_twiml(callId: UUID) -> Response:
    call_id = str(callId)
    if not _pending_sid(call_id) or call_id in state.support:
        raise HTTPException(404, "unknown call")
    return Response(phone.twiml(state.settings().public_base_url, call_id), media_type="application/xml")


@app.websocket(Route.TWILIO_WS)
async def twilio_stream(websocket: WebSocket) -> None:
    from pipecat.pipeline.runner import PipelineRunner

    from .pipeline import build_pipeline

    await websocket.accept()
    start = await _read_start(websocket)
    if start is None:
        return
    call_id = start.call_id
    if call_id in state.live_calls or call_id in state.support or _pending_sid(call_id) != start.call_sid:
        logger.warning(f"twilio stream refused for call {call_id}: not dialled by us or already live")
        await websocket.close(code=1008)
        return
    state.phone_pending.pop(call_id, None)
    state.live_calls[call_id] = f"twilio:{start.call_sid}"
    try:
        s = state.settings()
        transport = _twilio_transport(websocket, start)
        try:
            task = await build_pipeline(s, call_id, transport, chain=state.get_chain(), audio_sample_rate=8000, call_sid=start.call_sid)
        except Exception as e:
            logger.warning(f"phone call {call_id} not started: {e!r}")
            await websocket.close(code=1011)
            return
        await PipelineRunner(handle_sigint=False).run(task)
    finally:
        state.live_calls.pop(call_id, None)


def _phone_busy() -> bool:
    return any(_pending_sid(c) is not None for c in list(state.phone_pending)) or any(
        str(v).startswith("twilio:") for v in state.live_calls.values())


async def _twilio_form(request: Request) -> dict[str, str]:
    """The webhook's POST params, after checking Twilio signed them for this exact public URL."""
    s = state.settings()
    if not phone.inbound_configured(s):
        raise HTTPException(403, "PHONE_NOT_CONFIGURED")
    params = {k: str(v) for k, v in (await request.form()).items()}
    url = s.public_base_url + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not phone.signature_valid(s.twilio_auth_token, url, params, request.headers.get("X-Twilio-Signature")):
        logger.warning(f"twilio webhook refused: bad signature on {request.url.path}")
        raise HTTPException(403, "BAD_SIGNATURE")
    return params


@app.post(Route.TWILIO_SUPPORT_INCOMING)
async def twilio_support_incoming(request: Request) -> Response:
    """Twilio's Voice webhook for the number: a caller rings the desk, a PHONE support call starts and its audio streams in."""
    params = await _twilio_form(request)
    call_sid = params.get("CallSid")
    if not call_sid:
        raise HTTPException(400, "CallSid is required")
    brain = await state.new_support_brain(Channel.PHONE)
    call_id = brain.call.call_id
    brain.call.caller_ref = params.get("From") or None
    state.phone_pending[call_id] = (call_sid, time.monotonic())
    logger.info(f"support phone call {call_id} from {phone.mask(params.get('From') or '')} as {call_sid}")
    return Response(phone.twiml(state.settings().public_base_url, call_id, Route.TWILIO_SUPPORT_WS), media_type="application/xml")


@app.post(Route.SUPPORT_PHONE_CALL)
async def support_phone_call(body: PhoneNumberIn) -> dict:
    """The panel's "call me": the desk rings an allowed number and the answered call streams to the support agent."""
    s = state.settings()
    to = _allowed_number(body, s)
    if _phone_busy():
        raise HTTPException(409, "PHONE_BUSY")
    if not await phone.tunnel_up(s.public_base_url, transport=state.tunnel_transport):
        logger.warning("support phone call not placed: PUBLIC_BASE_URL/health did not answer")
        raise HTTPException(503, "TUNNEL_DOWN")
    brain = await state.new_support_brain(Channel.PHONE)
    call_id = brain.call.call_id
    brain.call.caller_ref = to
    state.phone_pending[call_id] = ("", time.monotonic())
    try:
        sid = await phone.dial(s, call_id, to, transport=state.twilio_transport, twiml_path=Route.TWILIO_SUPPORT_TWIML)
    except phone.DialError as e:
        state.phone_pending.pop(call_id, None)
        state.support.pop(call_id, None)
        await brain.finish(Outcome.ABANDONED)
        detail = phone.mask_numbers(str(e))
        logger.warning(f"support phone call {call_id} not placed: {detail}")
        raise HTTPException(502, detail) from None
    state.phone_pending[call_id] = (sid, time.monotonic())
    logger.info(f"support phone call {call_id} dialled as {sid} to {phone.mask(to)}")
    return {"call_id": call_id, "status": "dialling"}


@app.post(Route.TWILIO_SUPPORT_TWIML)
async def twilio_support_twiml(callId: UUID) -> Response:
    call_id = str(callId)
    if not _pending_sid(call_id) or call_id not in state.support:
        raise HTTPException(404, "unknown call")
    return Response(phone.twiml(state.settings().public_base_url, call_id, Route.TWILIO_SUPPORT_WS), media_type="application/xml")


def _twilio_transport(websocket: WebSocket, start: phone.StreamStart):
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

    s = state.settings()
    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            allowed_origins=[],
            serializer=TwilioFrameSerializer(stream_sid=start.stream_sid, call_sid=start.call_sid,
                                             account_sid=s.twilio_account_sid, auth_token=s.twilio_auth_token),
        ),
    )


async def _read_start(websocket: WebSocket) -> phone.StreamStart | None:
    try:
        async with asyncio.timeout(10):
            while True:
                msg = json.loads(await websocket.receive_text())
                if msg.get("event") == "start":
                    return phone.parse_start(msg)
    except Exception as e:
        logger.warning(f"twilio stream refused: {type(e).__name__}")
        await websocket.close(code=1008)
        return None


@app.websocket(Route.TWILIO_SUPPORT_WS)
async def twilio_support_stream(websocket: WebSocket) -> None:
    from pipecat.pipeline.runner import PipelineRunner

    from . import support_pipeline

    await websocket.accept()
    start = await _read_start(websocket)
    if start is None:
        return
    call_id = start.call_id
    brain = state.support.get(call_id)
    if brain is None or call_id in state.live_calls or _pending_sid(call_id) != start.call_sid:
        logger.warning(f"support stream refused for call {call_id}: not answered or dialled by us, or already live")
        await websocket.close(code=1008)
        return
    state.phone_pending.pop(call_id, None)
    state.live_calls[call_id] = f"twilio:{start.call_sid}"
    s = state.settings()
    brain.call.phone_call_sid = start.call_sid
    brain.call.transfer_to = s.human_agent_number or None
    try:
        task = support_pipeline.build_support_pipeline(s, brain, _twilio_transport(websocket, start), audio_sample_rate=8000)
        await PipelineRunner(handle_sigint=False).run(task)
    finally:
        state.live_calls.pop(call_id, None)
        state.support.pop(call_id, None)


@app.on_event("shutdown")
async def close_webrtc() -> None:
    if state.webrtc is not None:
        await state.webrtc.close()
