import asyncio
import time

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    EndWorkerFrame,
    ErrorFrame,
    FunctionCallResultProperties,
    TranscriptionFrame,
    TTSSpeakFrame,
    TTSTextFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.groq.stt import GroqSTTService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport

from . import phone
from .api_client import ApiUnavailable, RenewalsApi
from .config import Settings
from .edge_tts_service import EdgeTTSService
from .llm_chain import ChainConfigError, ChainState, build_live_switcher
from .prompt import system_prompt
from .tools import TOOL_SCHEMAS, run_tool

GOODBYE = "Thank you for your time. Goodbye."
LLM_FALLBACK = "Sorry, give me a moment."
LLM_FALLBACK_INTERVAL_SECS = 10.0
LLM_GIVE_UP_AFTER = 3
HANDOFF_TRANSFER_DELAY_SECS = 6.0  # time for the agent to say it is connecting them
LLM_GIVE_UP = "I'll ask a colleague to call you back shortly."


class TurnLog(BaseObserver):
    """Posts each final customer transcription and each spoken agent sentence to the call record, in order."""

    def __init__(self, api: RenewalsApi, call_id: str):
        super().__init__()
        self._api, self._call_id = api, call_id
        self._last: asyncio.Task | None = None

    async def on_push_frame(self, data: FramePushed):
        if not data.first_push:
            return
        frame = data.frame
        if isinstance(frame, TranscriptionFrame):
            role = "customer"
        elif isinstance(frame, TTSTextFrame):
            role = "agent"
        else:
            return
        if frame.text.strip():
            self._last = asyncio.create_task(self._post(self._last, role, frame.text.strip()))

    async def _post(self, previous: asyncio.Task | None, role: str, text: str) -> None:
        if previous is not None:
            await asyncio.gather(previous, return_exceptions=True)
        try:
            await self._api.turn(self._call_id, role, text)
        except ApiUnavailable as e:
            logger.warning(f"turn not recorded: {e}")

    async def flush(self) -> None:
        if self._last is not None:
            await asyncio.gather(self._last, return_exceptions=True)


def _tools_schema() -> ToolsSchema:
    return ToolsSchema(
        standard_tools=[
            FunctionSchema(
                name=t["function"]["name"],
                description=t["function"]["description"],
                properties=t["function"]["parameters"]["properties"],
                required=t["function"]["parameters"]["required"],
            )
            for t in TOOL_SCHEMAS
        ]
    )


async def build_pipeline(
    settings: Settings,
    call_id: str,
    transport: BaseTransport,
    api: RenewalsApi | None = None,
    chain: ChainState | None = None,
    audio_sample_rate: int | None = None,
    call_sid: str | None = None,
) -> PipelineWorker:
    chain = chain or ChainState(settings.llm_chain)
    api = api or RenewalsApi(settings)
    try:
        call = await api.call(call_id)
    except ApiUnavailable:
        await api.aclose()
        raise
    greeting = call.get("greeting")
    if call.get("error") or not greeting:
        await api.aclose()
        raise LookupError(f"unknown call {call_id}")

    stt = GroqSTTService(api_key=settings.groq_api_key, settings=GroqSTTService.Settings(model=settings.stt_model))
    try:
        llm = build_live_switcher(chain, system_prompt(greeting))
    except ChainConfigError:
        await api.aclose()
        raise

    memory: dict = {}

    async def handle_tool(params: FunctionCallParams) -> None:
        try:
            result = await run_tool(api, call_id, params.function_name, dict(params.arguments or {}), memory)
        except ApiUnavailable:
            result = {"error": "API_UNAVAILABLE", "mustHandoff": True}
        if params.function_name != "end_call":
            await params.result_callback(result)
            if params.function_name == "handoff_to_human" and "error" not in result and call_sid and settings.human_agent_number:
                asyncio.create_task(_transfer_after_reply())
            return
        await params.result_callback(result, properties=FunctionCallResultProperties(run_llm=False))
        await llm.active_llm.push_frame(TTSSpeakFrame(GOODBYE))
        await llm.active_llm.push_frame(EndWorkerFrame(reason="end_call"))

    async def _transfer_after_reply() -> None:
        """Phone hand-off: let the agent finish its sentence, then dial the call through to a person."""
        await asyncio.sleep(HANDOFF_TRANSFER_DELAY_SECS)
        try:
            await phone.transfer(settings, call_sid, settings.human_agent_number)
        except phone.DialError as e:
            logger.warning(f"transfer to a person failed: {e}")

    for tool in TOOL_SCHEMAS:
        llm.register_function(tool["function"]["name"], handle_tool)

    context = LLMContext([{"role": "assistant", "content": greeting}], tools=_tools_schema())
    aggregators = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.2)),
            user_turn_stop_timeout=2.0,
            empty_user_turn=None,
        ),
    )
    tts = EdgeTTSService(voice=settings.tts_voice)

    turn_log = TurnLog(api, call_id)
    task = PipelineWorker(
        Pipeline(
            [transport.input(), stt, aggregators.user(), llm, tts, transport.output(), aggregators.assistant()]
        ),
        params=PipelineParams(
            enable_metrics=True,
            **({"audio_in_sample_rate": audio_sample_rate, "audio_out_sample_rate": audio_sample_rate}
               if audio_sample_rate else {}),
        ),
        observers=[turn_log],
    )

    @transport.event_handler("on_client_connected")
    async def on_connected(_transport, _client):
        await task.queue_frames([TTSSpeakFrame(greeting, append_to_context=False)])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(_transport, _client):
        await task.cancel()

    last_fallback: float | None = None
    fallbacks = 0
    answers_at_fallback = -1
    gave_up = False

    @task.event_handler("on_pipeline_error")
    async def on_error(_task, frame: ErrorFrame):
        nonlocal last_fallback, fallbacks, answers_at_fallback, gave_up
        if gave_up or (frame.processor is not llm and frame.processor not in llm.llms):
            return
        now = time.monotonic()
        if last_fallback is not None and now - last_fallback < LLM_FALLBACK_INTERVAL_SECS:
            return
        last_fallback = now
        fallbacks = fallbacks + 1 if llm.answers == answers_at_fallback else 1
        answers_at_fallback = llm.answers
        frames = [TTSSpeakFrame(LLM_FALLBACK, append_to_context=False)]
        if fallbacks >= LLM_GIVE_UP_AFTER:
            gave_up = True
            try:
                await api.handoff(call_id, "LLM_UNAVAILABLE")
            except ApiUnavailable as e:
                logger.warning(f"handoff not recorded: {e}")
            frames += [TTSSpeakFrame(LLM_GIVE_UP, append_to_context=False), EndWorkerFrame(reason="llm_unavailable")]
        await task.queue_frames(frames)

    closed = False

    @task.event_handler("on_pipeline_finished")
    async def on_finished(_task, _frame):
        nonlocal closed
        if closed:
            return
        closed = True
        await turn_log.flush()
        try:
            await api.end(call_id)
        except ApiUnavailable as e:
            logger.warning(f"call not ended: {e}")
        await api.aclose()

    return task
