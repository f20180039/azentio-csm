"""Live browser call for the front desk: mic → voice detection → speech-to-text → SupportBrain → voice. The same brain
serves typed and recorded-audio calls, so all three behave alike and record the same turn metadata."""
import asyncio

from loguru import logger
from pipecat.frames.frames import (
    EndWorkerFrame,
    Frame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import BaseTransport

from .edge_tts_service import EdgeTTSService
from .speech import build_stt, build_vad, keep_transcript
from .support_brain import SupportBrain
from .support_prompt import GREETING

GOODBYE_GRACE_SECS = 4.0
FALLBACK = "Sorry, I didn't catch that. Could you say it again?"
SYSTEM_DOWN = "Sorry, I'm having trouble reaching our systems. Please hold on or try again in a moment."


class SupportResponder(FrameProcessor):
    """Turns each final transcript into one brain reply. A caller who starts speaking interrupts the reply in progress."""

    def __init__(self, brain: SupportBrain, **kwargs):
        super().__init__(**kwargs)
        self._brain = brain
        self._busy: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStartedSpeakingFrame):
            await self.broadcast_interruption()
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            text = keep_transcript(frame)
            if text:
                self._busy = self.create_task(self._answer(text))
            return
        await self.push_frame(frame, direction)

    async def _answer(self, text: str) -> None:
        try:
            turn = await self._brain.reply(text)
            reply = turn.text or FALLBACK
        except Exception as e:  # the caller always hears something
            logger.warning(f"support reply failed: {e!r}")
            reply, turn = SYSTEM_DOWN, None
        await self.push_frame(TTSSpeakFrame(reply))
        if turn is not None and turn.ended:
            await asyncio.sleep(GOODBYE_GRACE_SECS)
            await self.push_frame(EndWorkerFrame(reason="end_call"))


def build_support_pipeline(settings, brain: SupportBrain, transport: BaseTransport, audio_sample_rate: int | None = None) -> PipelineWorker:
    responder = SupportResponder(brain)
    task = PipelineWorker(
        Pipeline([transport.input(), VADProcessor(vad_analyzer=build_vad()), build_stt(settings), responder,
                  EdgeTTSService(voice=settings.tts_voice), transport.output()]),
        params=PipelineParams(enable_metrics=True, **({"audio_in_sample_rate": audio_sample_rate, "audio_out_sample_rate": audio_sample_rate}
                                                     if audio_sample_rate else {})),
    )

    @transport.event_handler("on_client_connected")
    async def on_connected(_transport, _client):
        await task.queue_frames([TTSSpeakFrame(GREETING)])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(_transport, _client):
        await task.cancel()

    finished = False

    @task.event_handler("on_pipeline_finished")
    async def on_finished(_task, _frame):
        nonlocal finished
        if not finished:
            finished = True
            await brain.finish()

    return task
