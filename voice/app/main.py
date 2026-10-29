from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel

from .api_client import ApiUnavailable, RenewalsApi
from .brain import CallBrain, ChatClient, GroqChatClient
from .config import Settings, load_settings
from .prompt import system_prompt


class State:
    def __init__(self) -> None:
        self.api: RenewalsApi | None = None
        self.llm: ChatClient | None = None
        self.brains: dict[str, CallBrain] = {}
        self.webrtc = None
        self.live_calls: dict[str, str | None] = {}
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

    def get_llm(self) -> ChatClient:
        if self.llm is None:
            self.llm = GroqChatClient(self.settings())
        return self.llm


state = State()
app = FastAPI(title="Renewal Desk voice")


class TextCallIn(BaseModel):
    callId: str


class TextTurnIn(BaseModel):
    callId: str
    text: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/text-call")
async def text_call(body: TextCallIn) -> dict:
    existing = state.brains.get(body.callId)
    if existing is not None:
        return {"greeting": existing.greeting}
    api = state.get_api()
    try:
        call = await api.call(body.callId)
    except ApiUnavailable as e:
        raise HTTPException(502, "renewals API unavailable") from e
    if call.get("error") or not call.get("greeting"):
        raise HTTPException(404, "unknown call")
    brain = CallBrain(state.get_llm(), api, body.callId, system_prompt(call["greeting"]))
    await brain.say(call["greeting"])
    brain.greeting = call["greeting"]
    state.brains[body.callId] = brain
    return {"greeting": call["greeting"]}


@app.post("/v1/text-turn")
async def text_turn(body: TextTurnIn) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "text must not be blank")
    brain = state.brains.get(body.callId)
    if brain is None:
        raise HTTPException(404, "unknown call")
    try:
        turn = await brain.reply(body.text)
    except ApiUnavailable as e:
        raise HTTPException(502, "renewals API unavailable") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, "language model unavailable") from e
    return {
        "reply": turn.text,
        "toolCalls": [{"name": t.name, "args": t.args, "result": t.result} for t in turn.tool_calls],
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
            task = await build_pipeline(state.settings(), call_id, transport)
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


@app.on_event("shutdown")
async def close_webrtc() -> None:
    if state.webrtc is not None:
        await state.webrtc.close()
