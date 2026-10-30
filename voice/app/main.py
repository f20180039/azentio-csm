import asyncio
import json
import os
import time
from uuid import UUID
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCPatchRequest

from . import phone
from .api_client import ApiUnavailable, RenewalsApi
from .brain import CallBrain, ChatClient
from .config import Settings, load_settings
from .llm_chain import ChainChatClient, ChainState, LLMUnavailable
from .prompt import system_prompt


class State:
    def __init__(self) -> None:
        self.api: RenewalsApi | None = None
        self.llm: ChatClient | None = None
        self.chain: ChainState | None = None
        self.brains: dict[str, CallBrain] = {}
        self.webrtc = None
        self.live_calls: dict[str, str | None] = {}
        self.phone_pending: dict[str, tuple[str, float]] = {}
        self.twilio_transport: httpx.AsyncBaseTransport | None = None
        self.tunnel_transport: httpx.AsyncBaseTransport | None = None
        self._settings: Settings | None = None

    def settings(self) -> Settings:
        if self._settings is None:
            env_file = Path(__file__).resolve().parents[2] / ".env"
            self._settings = load_settings(env_file if env_file.exists() else None)
        return self._settings

    def get_api(self) -> RenewalsApi:
        if self.api is None:
            self.api = RenewalsApi(self.settings())
        return self.api

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
PUBLIC_PATHS = ("/ws/twilio", "/twilio/twiml", "/health")


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


@app.get("/health")
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


class OfferIn(BaseModel):
    sdp: str
    type: str
    pc_id: str | None = None
    restart_pc: bool | None = None
    requestData: dict | None = None


@app.post("/api/offer")
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


@app.patch("/api/offer")
async def ice_candidate(body: SmallWebRTCPatchRequest) -> dict:
    """Trickled ICE candidates from the browser transport, forwarded to Pipecat's own handler."""
    if state.webrtc is None:
        raise HTTPException(404, "Peer connection not found")
    await state.webrtc.handle_patch_request(body)
    return {"status": "success"}


class PhoneCallIn(BaseModel):
    callId: UUID
    to: str | None = None
    numberId: str | None = None


def _pending_sid(call_id: str) -> str | None:
    entry = state.phone_pending.get(call_id)
    if entry is None:
        return None
    if time.monotonic() - entry[1] > phone.PENDING_TTL_SECS:
        state.phone_pending.pop(call_id, None)
        return None
    return entry[0]


@app.get("/v1/phone/allowed")
async def phone_allowed() -> dict:
    s = state.settings()
    if not phone.configured(s):
        return {"configured": False, "numbers": []}
    return {"configured": True, "numbers": [{"id": str(i), "masked": phone.mask(n)} for i, n in enumerate(s.twilio_allowed_to)]}


@app.post("/v1/phone-call")
async def phone_call(body: PhoneCallIn) -> dict:
    s = state.settings()
    call_id = str(body.callId)
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
    if call_id in state.live_calls or _pending_sid(call_id) is not None:
        raise HTTPException(409, "CALL_IN_PROGRESS")
    if any(_pending_sid(c) is not None for c in list(state.phone_pending)) or any(
        str(v).startswith("twilio:") for v in state.live_calls.values()
    ):
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


@app.post("/twilio/twiml")
async def twilio_twiml(callId: UUID) -> Response:
    call_id = str(callId)
    if not _pending_sid(call_id):
        raise HTTPException(404, "unknown call")
    return Response(phone.twiml(state.settings().public_base_url, call_id), media_type="application/xml")


@app.websocket("/ws/twilio")
async def twilio_stream(websocket: WebSocket) -> None:
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

    from .pipeline import build_pipeline

    await websocket.accept()
    try:
        start = None
        async with asyncio.timeout(10):
            while start is None:
                msg = json.loads(await websocket.receive_text())
                if msg.get("event") == "start":
                    start = phone.parse_start(msg)
    except Exception as e:
        logger.warning(f"twilio stream refused: {type(e).__name__}")
        await websocket.close(code=1008)
        return
    call_id = start.call_id
    if call_id in state.live_calls or _pending_sid(call_id) != start.call_sid:
        logger.warning(f"twilio stream refused for call {call_id}: not dialled by us or already live")
        await websocket.close(code=1008)
        return
    state.phone_pending.pop(call_id, None)
    state.live_calls[call_id] = f"twilio:{start.call_sid}"
    try:
        s = state.settings()
        transport = FastAPIWebsocketTransport(
            websocket=websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                allowed_origins=[],
                serializer=TwilioFrameSerializer(
                    stream_sid=start.stream_sid,
                    call_sid=start.call_sid,
                    account_sid=s.twilio_account_sid,
                    auth_token=s.twilio_auth_token,
                ),
            ),
        )
        try:
            task = await build_pipeline(s, call_id, transport, chain=state.get_chain(), audio_sample_rate=8000)
        except Exception as e:
            logger.warning(f"phone call {call_id} not started: {e!r}")
            await websocket.close(code=1011)
            return
        await PipelineRunner(handle_sigint=False).run(task)
    finally:
        state.live_calls.pop(call_id, None)


@app.on_event("shutdown")
async def close_webrtc() -> None:
    if state.webrtc is not None:
        await state.webrtc.close()
