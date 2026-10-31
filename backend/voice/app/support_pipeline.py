"""Live browser call for the front desk: mic → voice detection → speech-to-text → SupportBrain → voice. The same brain
serves typed and recorded-audio calls, so all three behave alike and record the same turn metadata."""
import asyncio
import os

from loguru import logger
from pipecat.frames.frames import (
    EndWorkerFrame,
    Frame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
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


SETTLE_SECS = float(os.environ.get("VOICE_TURN_SETTLE_SECS", "1.0"))  # quiet time after the caller's last words before the agent answers


class TurnGate:
    """Decides when the caller's turn is complete and whether a finished reply is still wanted.

    Voice detection can split one sentence into several transcripts ("I am looking for a..." / "status of my loan").
    Transcripts are gathered until the caller has stopped speaking for SETTLE_SECS, then answered once. Every time the
    caller starts speaking the generation moves on, so a reply prepared for an earlier generation is never spoken."""

    def __init__(self, answer, settle: float = SETTLE_SECS):
        self._answer, self._settle = answer, settle
        self.generation = 0
        self.speaking = False
        self._parts: list[str] = []
        self._timer: asyncio.Task | None = None
        self._replies: set[asyncio.Task] = set()

    def user_started(self) -> None:
        self.speaking = True
        self.generation += 1
        self._cancel_timer()

    def user_stopped(self) -> None:
        self.speaking = False
        if self._parts:
            self._arm()

    def transcript(self, text: str) -> None:
        self._parts.append(text)
        self._arm()

    def is_current(self, generation: int) -> bool:
        return generation == self.generation and not self.speaking

    def _arm(self) -> None:
        self._cancel_timer()
        self._timer = asyncio.create_task(self._fire())

    def _cancel_timer(self) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()

    async def _fire(self) -> None:
        await asyncio.sleep(self._settle)
        if self.speaking or not self._parts:
            return
        text, self._parts = " ".join(self._parts), []
        # the reply runs on its own: a caller who speaks again cancels the timer, never a reply half-way through a tool call
        task = asyncio.create_task(self._answer(text, self.generation))
        self._replies.add(task)
        task.add_done_callback(self._replies.discard)


class SupportResponder(FrameProcessor):
    """Answers each completed caller turn with one brain reply. The caller starting to speak cuts the agent off: audio
    already playing is interrupted, and a reply still being prepared is dropped instead of being read out later."""

    def __init__(self, brain: SupportBrain, **kwargs):
        super().__init__(**kwargs)
        self._brain = brain
        self._gate = TurnGate(self._answer)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._gate.user_started()
            await self.broadcast_interruption()
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            self._gate.user_stopped()
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, TranscriptionFrame) and direction == FrameDirection.DOWNSTREAM:
            text = keep_transcript(frame)
            if text:
                self._gate.transcript(text)
            return
        await self.push_frame(frame, direction)

    async def _answer(self, text: str, generation: int) -> None:
        try:
            turn = await self._brain.reply(text)
            reply = turn.text or FALLBACK
        except Exception as e:  # the caller always hears something
            logger.warning(f"support reply failed: {e!r}")
            reply, turn = SYSTEM_DOWN, None
        if not self._gate.is_current(generation):
            self._brain.mark_unheard()
            logger.debug("reply dropped: the caller spoke again before it was played")
            return
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
