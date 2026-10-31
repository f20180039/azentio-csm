"""The speech front end shared by live calls and recorded-audio simulation: voice detection settings, the speech-to-text
service, and the filter that drops transcripts the model invents from noise. Values are tuned from spikes/stt-bench."""
import re

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import TranscriptionFrame
from pipecat.services.groq.stt import GroqSTTService

VAD_STOP_SECS = 0.2
DOMAIN_PROMPT = ("Azentio Demo Bank customer service call. EMI, instalment, NACH, KYC, loan statement, repayment schedule, "
                 "SR-40102, CMP-50011, personal loan, vehicle loan, home loan, policy, claim.")

# Whisper's well-known inventions on silence and noise
PHANTOMS = {"thank you", "thanks for watching", "thank you for watching", "you", "bye", "so", "okay", "uh", "um"}
_PUNCT = re.compile(r"[^\w\s]")


def build_vad() -> SileroVADAnalyzer:
    return SileroVADAnalyzer(params=VADParams(stop_secs=VAD_STOP_SECS))


def build_stt(settings) -> GroqSTTService:
    return GroqSTTService(api_key=settings.groq_api_key, settings=GroqSTTService.Settings(model=settings.stt_model))


def is_phantom(text: str) -> bool:
    words = _PUNCT.sub("", text).strip().lower()
    return not words or words in PHANTOMS


def keep_transcript(frame: TranscriptionFrame) -> str | None:
    text = (frame.text or "").strip()
    return None if is_phantom(text) else text
