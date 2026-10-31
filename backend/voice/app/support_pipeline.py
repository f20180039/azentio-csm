"""Live browser call for the front desk: mic → voice detection → speech-to-text → SupportBrain → voice. The same brain
serves typed and recorded-audio calls, so all three behave alike and record the same turn metadata."""
import asyncio
import os

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
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

from . import phone
from .edge_tts_service import EdgeTTSService
from .recordings import join_wavs
from .speech import CallLanguage, build_stt, build_vad, keep_transcript
from .support_brain import SupportBrain, SupportTurn
from .support_prompt import GREETING
from .support_tools import CallSession
from .vocab import HandoffMode, Outcome, SupportTool

GOODBYE_GRACE_SECS = 4.0
FALLBACK = "Sorry, I didn't catch that. Could you say it again?"
SYSTEM_DOWN = "Sorry, I'm having trouble reaching our systems. Please hold on or try again in a moment."


SETTLE_SECS = float(os.environ.get("VOICE_TURN_SETTLE_SECS", "1.5"))  # quiet time after the caller's last words before the agent answers
IDLE_PROMPT_SECS = float(os.environ.get("VOICE_IDLE_PROMPT_SECS", "5"))  # silence after the agent speaks before it checks in
IDLE_HANGUP_SECS = float(os.environ.get("VOICE_IDLE_HANGUP_SECS", "3"))  # further silence after the check-in before it hangs up
STILL_THERE = "Are you still there?"
NOISY_BEFORE_ASKING = 2  # unusable, noise-only segments in a row before the agent asks the caller to repeat
NOISY_ASK = "Sorry, there's some background noise. Could you say that again?"
IDLE_GOODBYE = "I haven't heard anything, so I'll end the call now. Thank you for calling Azentio Demo Bank."


class IdleWatch:
    """Silence after the agent finishes speaking: check in once after `prompt_after`, hang up `hangup_after` later.
    Any caller speech resets it; it is paused while the caller speaks or a reply is being prepared."""

    def __init__(self, on_prompt, on_hangup, prompt_after: float = IDLE_PROMPT_SECS, hangup_after: float = IDLE_HANGUP_SECS):
        self._on_prompt, self._on_hangup = on_prompt, on_hangup
        self._prompt_after, self._hangup_after = prompt_after, hangup_after
        self.prompted = False
        self._timer: asyncio.Task | None = None

    def caller_active(self) -> None:
        self.prompted = False
        self.pause()

    def pause(self) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()

    def agent_done(self) -> None:
        self.pause()
        self._timer = asyncio.create_task(self._wait())

    async def _wait(self) -> None:
        if not self.prompted:
            await asyncio.sleep(self._prompt_after)
            self.prompted = True
            await self._on_prompt()
        else:
            await asyncio.sleep(self._hangup_after)
            await self._on_hangup()


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
        self._audio: list[bytes] = []
        self.audio_by_generation: dict[int, list[bytes]] = {}
        self._timer: asyncio.Task | None = None
        self._replies: set[asyncio.Task] = set()

    @property
    def busy(self) -> bool:
        """A caller turn is being gathered or answered, so silence is not idleness."""
        return bool(self._parts) or any(not t.done() for t in self._replies)

    def user_started(self) -> None:
        self.speaking = True
        self.generation += 1
        self._cancel_timer()

    def user_stopped(self) -> None:
        self.speaking = False
        if self._parts:
            self._arm()

    def transcript(self, text: str, audio: bytes | None = None) -> None:
        self._parts.append(text)
        if audio:
            self._audio.append(audio)
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
        if self._audio:
            self.audio_by_generation[self.generation], self._audio = self._audio, []
        # the reply runs on its own: a caller who speaks again cancels the timer, never a reply half-way through a tool call
        task = asyncio.create_task(self._answer(text, self.generation))
        self._replies.add(task)
        task.add_done_callback(self._replies.discard)


def wants_transfer(turn: SupportTurn) -> bool:
    return any(t.name == SupportTool.ESCALATE_TO_HUMAN and isinstance(t.result, dict)
               and (t.result.get("handoff") or {}).get("mode") == HandoffMode.TRANSFER for t in turn.tool_calls)


async def transfer_after_reply(settings, call: CallSession, delay: float = phone.HANDOFF_TRANSFER_DELAY_SECS,
                               transport=None) -> None:
    """Phone hand-off: let the agent finish saying it is connecting them, then dial the live call through to a person."""
    await asyncio.sleep(delay)
    try:
        await phone.transfer(settings, call.phone_call_sid, call.transfer_to, transport=transport)
    except phone.DialError as e:
        logger.warning(f"transfer to a person failed: {e}")


class SupportResponder(FrameProcessor):
    """Answers each completed caller turn with one brain reply. The caller starting to speak cuts the agent off: audio
    already playing is interrupted, and a reply still being prepared is dropped instead of being read out later."""

    def __init__(self, brain: SupportBrain, settings=None, **kwargs):
        super().__init__(**kwargs)
        self._brain = brain
        self._settings = settings
        self._gate = TurnGate(self._answer)
        self._idle = IdleWatch(self._check_in, self._hang_up)
        self._noisy = 0
        self.abandoned = False
        self._transfers: set[asyncio.Task] = set()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, BotStoppedSpeakingFrame):
            if not self._gate.busy:
                self._idle.agent_done()
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, BotStartedSpeakingFrame):
            self._idle.pause()
            await self.push_frame(frame, direction)
            return
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._idle.caller_active()
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
                self._noisy = 0
                self._idle.caller_active()
                self._gate.transcript(text, getattr(frame, "audio_wav", None))
            else:
                self._noisy += 1  # the caller made sound but nothing usable came through
                if self._noisy == NOISY_BEFORE_ASKING and not self._gate.busy:
                    self._noisy = 0
                    await self.push_frame(TTSSpeakFrame(NOISY_ASK))
            return
        await self.push_frame(frame, direction)

    async def _check_in(self) -> None:
        await self.push_frame(TTSSpeakFrame(STILL_THERE))

    async def _hang_up(self) -> None:
        self.abandoned = True
        await self.push_frame(TTSSpeakFrame(IDLE_GOODBYE))
        await asyncio.sleep(GOODBYE_GRACE_SECS)
        await self.push_frame(EndWorkerFrame(reason="caller_silent"))

    async def _answer(self, text: str, generation: int) -> None:
        try:
            audio = join_wavs(self._gate.audio_by_generation.pop(generation, []))
            turn = await (self._brain.reply(text, audio=audio) if audio else self._brain.reply(text))
            reply = turn.text or FALLBACK
        except Exception as e:  # the caller always hears something
            logger.warning(f"support reply failed: {e!r}")
            reply, turn = SYSTEM_DOWN, None
        if turn is not None and self._settings is not None and wants_transfer(turn):
            # the escalation is already raised, so the transfer goes ahead even if this reply is never played
            task = asyncio.create_task(transfer_after_reply(self._settings, self._brain.call))
            self._transfers.add(task)
            task.add_done_callback(self._transfers.discard)
        if not self._gate.is_current(generation):
            self._brain.mark_unheard()
            logger.debug("reply dropped: the caller spoke again before it was played")
            return
        await self.push_frame(TTSSpeakFrame(reply))
        if turn is not None and turn.ended:
            await asyncio.sleep(GOODBYE_GRACE_SECS)
            await self.push_frame(EndWorkerFrame(reason="end_call"))


def build_support_pipeline(settings, brain: SupportBrain, transport: BaseTransport, audio_sample_rate: int | None = None) -> PipelineWorker:
    responder = SupportResponder(brain, settings)
    language = CallLanguage(settings.voice_languages)  # heard by speech-to-text, followed by the voice
    task = PipelineWorker(
        Pipeline([transport.input(), VADProcessor(vad_analyzer=build_vad()), build_stt(settings, language), responder,
                  EdgeTTSService(voice=settings.tts_voice, call_language=language), transport.output()]),
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
            await brain.finish(Outcome.ABANDONED if responder.abandoned and not brain.call.refs else None)

    return task
