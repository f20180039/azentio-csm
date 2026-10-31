"""The speech front end shared by live calls and recorded-audio simulation: voice detection settings, the speech-to-text
service, and the filter that drops transcripts the model invents from noise. Values are tuned from spikes/stt-bench."""
import re

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import TranscriptionFrame
from pipecat.services.groq.stt import GroqSTTService

VAD_STOP_SECS = 0.2
VAD_CONFIDENCE = 0.6        # Silero speech probability needed per 32 ms window
MIN_SPEECH_SECS = 0.25      # shorter bursts (a cough, a door) start no segment
PRE_ROLL_SECS = 0.2         # keep the start of the first word
POST_ROLL_SECS = 0.2
MERGE_GAP_SECS = 0.6        # a pause inside a sentence stays one segment
LANGUAGE = "en"
NO_SPEECH_PROB_MAX = 0.6    # Whisper's own "this was not speech" estimate
AVG_LOGPROB_MIN = -1.0
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


def is_invented_segment(segment: dict) -> bool:
    """A Whisper segment the model itself flags as probably not speech, or one that is only a known phantom phrase."""
    return (segment.get("no_speech_prob", 0.0) > NO_SPEECH_PROB_MAX and segment.get("avg_logprob", 0.0) < AVG_LOGPROB_MIN) \
        or is_phantom(segment.get("text", ""))


def keep_transcript(frame: TranscriptionFrame) -> str | None:
    text = (frame.text or "").strip()
    return None if is_phantom(text) else text
