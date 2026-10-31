"""The speech front end shared by live calls and recorded-audio simulation: voice detection settings, the speech-to-text
service, and the filter that drops transcripts the model invents from noise. Values are tuned from spikes/stt-bench."""
import os
import re

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import TranscriptionFrame
from pipecat.services.groq.stt import GroqSTTService
from pipecat.transcriptions.language import Language

from .vocab import SpeechLanguage

# Live voice detection (docs/stt-benchmark.md): stopping at 0.4 s instead of 0.2 s splits ~30% fewer sentences in two,
# so fewer speech-to-text requests and fewer half-sentence turns, for 0.2 s more end-of-turn wait.
VAD_CONFIDENCE = float(os.environ.get("VOICE_VAD_CONFIDENCE", "0.7"))
VAD_MIN_VOLUME = float(os.environ.get("VOICE_VAD_MIN_VOLUME", "0.6"))
VAD_START_SECS = float(os.environ.get("VOICE_VAD_START_SECS", "0.3"))  # 0.3 s of speech before a segment opens: clicks and knocks don't
VAD_STOP_SECS = 0.4
# Recorded-audio trimming
MIN_SPEECH_SECS = 0.25      # shorter bursts (a cough, a door) start no segment
PRE_ROLL_SECS = 0.2         # keep the start of the first word
POST_ROLL_SECS = 0.2
MERGE_GAP_SECS = 0.6        # a pause inside a sentence stays one segment
LANGUAGE = SpeechLanguage.ENGLISH.value
# Groq's turbo always reports no_speech_prob 0, so log-probability carries the filter (removed 5/20 false transcripts, 0 speech lost)
NO_SPEECH_PROB_MAX = 0.5
AVG_LOGPROB_MIN = -0.7
# The benchmark's prompt format (WER 4.6% → 3.7%, noisy 7.3% → 5.1%), with this bank's reference prefixes
DOMAIN_PROMPT = "Bank customer call. EMI, NACH, KYC, instalment, statement, SR-40102, CMP-50011, PL-31002, VL-31003, HP-77001."
# Kannada (docs/stt-benchmark.md, "Kannada"): with the English prompt and no pinned language, Whisper wrote Kannada speech
# romanised or in Telugu script; Kannada words in the prompt keep it in Kannada script. Groq's detected-language field named
# the Kannada clips English, Tamil or Hindi, so the call's language is read from the transcript's script instead.
BILINGUAL_PROMPT = "Bank customer call. ಬ್ಯಾಂಕ್ ಗ್ರಾಹಕರ ಕರೆ. EMI, ಸಾಲ, ಲೋನ್, ಖಾತೆ, ಸ್ಟೇಟ್‌ಮೆಂಟ್, ಕಂತು, NACH, KYC, statement, SR-40102."
KANNADA_PROMPT = "ಬ್ಯಾಂಕ್ ಗ್ರಾಹಕರ ಕರೆ. EMI, ಸಾಲ, ಲೋನ್, ಖಾತೆ, ಸ್ಟೇಟ್‌ಮೆಂಟ್, ಕಂತು, SR-40102."
KANNADA_VOICE = "kn-IN-SapnaNeural"
_KANNADA_CHAR = re.compile(r"[ಀ-೿]")
_LETTER = re.compile(r"[^\W\d_]")

# Whisper's well-known inventions on silence and noise. Not "okay" or "bye": callers say those.
PHANTOMS = {"thank you", "thanks for watching", "thank you for watching", "you", "thank you so much", "please subscribe"}
_PUNCT = re.compile(r"[^\w\s]")

REF_PREFIXES = ("SR", "CMP", "RQ", "ESC", "PL", "VL", "HL", "LA", "HP", "MP", "CLM", "TXN")
_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "to": "2", "too": "2", "three": "3", "four": "4", "for": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "ate": "8", "nine": "9"}
_COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "double": 2, "triple": 3, "quadruple": 4}
_PLURALS = {"zeros": "0", "zeroes": "0", "ones": "1", "twos": "2", "threes": "3", "fours": "4",
            "fives": "5", "sixes": "6", "sevens": "7", "eights": "8", "nines": "9"}

_TOKEN = r"(?:\d+|" + "|".join(sorted(_DIGIT_WORDS, key=len, reverse=True)) + r")\b"
_SPELLED_PREFIX = re.compile(r"\b(" + "|".join(" ?".join(p) for p in REF_PREFIXES) + r")\b(?=[\s.-]*" + _TOKEN + ")", re.I)
_REF = re.compile(r"\b(" + "|".join(REF_PREFIXES) + r")[\s.-]*(" + _TOKEN + r"(?:[\s.-]+" + _TOKEN + r"){0,7})", re.I)


def _to_digit(s: str) -> str:
    s = s.lower()
    return _DIGIT_WORDS.get(s, s if s.isdigit() else "")


def _to_count(s: str) -> int:
    s = s.lower()
    return int(s) if s.isdigit() else _COUNTS.get(s, 1)


def normalise_spoken_digits(text: str) -> str:
    """Expands spoken digit multipliers like '4 times 0' -> '0000', 'triple zero' -> '000', 'double 5' -> '55'."""
    if not text:
        return text

    def repl_times(m: re.Match) -> str:
        count = _to_count(m.group(1))
        d = _to_digit(m.group(2))
        return (d * count) if d and 1 <= count <= 10 else m.group(0)

    def repl_mult(m: re.Match) -> str:
        count = _to_count(m.group(1))
        d = _to_digit(m.group(2))
        return (d * count) if d and 1 <= count <= 10 else m.group(0)

    def repl_plural(m: re.Match) -> str:
        count = _to_count(m.group(1))
        d = _PLURALS.get(m.group(2).lower(), "")
        return (d * count) if d and 1 <= count <= 10 else m.group(0)

    p_count = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine)"
    p_digit = r"(?:\d+|zero|oh|one|two|three|four|five|six|seven|eight|nine)"
    p_mult = r"(?:double|triple|quadruple)"
    p_plural = r"(?:zeroes|zeros|ones|twos|threes|fours|fives|sixes|sevens|eights|nines)"

    text = re.sub(rf"\b({p_count})\s+times\s+({p_digit})\b", repl_times, text, flags=re.I)
    text = re.sub(rf"\b({p_mult})\s+({p_digit})\b", repl_mult, text, flags=re.I)
    text = re.sub(rf"\b({p_count})\s+({p_plural})\b", repl_plural, text, flags=re.I)
    return text


def normalise_refs(text: str) -> str:
    """'S R four zero one zero two' and 'SR for 8213' → 'SR-40102' and 'SR-48213', so ticket and loan references survive accents."""
    text = normalise_spoken_digits(text)
    text = _SPELLED_PREFIX.sub(lambda m: m.group(1).replace(" ", "").upper(), text)

    def fix(m: re.Match) -> str:
        digits = "".join(_DIGIT_WORDS.get(p.lower(), p) for p in re.split(r"[\s.-]+", m.group(2)) if p)
        return f"{m.group(1).upper()}-{digits}" if 4 <= len(digits) <= 8 else m.group(0)
    return _REF.sub(fix, text)


def is_mostly_kannada(text: str | None) -> bool:
    letters = _LETTER.findall(text or "")
    return bool(letters) and 2 * sum(1 for c in letters if _KANNADA_CHAR.match(c)) >= len(letters)


class CallLanguage:
    """The language one call is in: Kannada from a mostly-Kannada transcript until the caller speaks English again."""

    def __init__(self, enabled: tuple[SpeechLanguage, ...] = (SpeechLanguage.ENGLISH,)):
        self.enabled = enabled
        self.current = SpeechLanguage.ENGLISH if SpeechLanguage.ENGLISH in enabled else enabled[0]

    @property
    def detects(self) -> bool:
        """Several languages enabled: Whisper detects the language instead of being pinned to one."""
        return len(self.enabled) > 1

    def heard(self, text: str | None) -> None:
        if self.detects and _LETTER.search(text or ""):
            self.current = SpeechLanguage.KANNADA if is_mostly_kannada(text) else SpeechLanguage.ENGLISH

    def stt_language(self) -> str | None:
        return None if self.detects else self.enabled[0].value

    def stt_prompt(self) -> str:
        if SpeechLanguage.KANNADA not in self.enabled:
            return DOMAIN_PROMPT
        return KANNADA_PROMPT if self.current == SpeechLanguage.KANNADA else BILINGUAL_PROMPT


def voice_for(text: str, default: str, call: CallLanguage | None = None) -> str:
    """Kannada voice for a reply in Kannada script or during a Kannada call; the configured voice otherwise."""
    kannada_call = call is not None and call.current == SpeechLanguage.KANNADA
    return KANNADA_VOICE if is_mostly_kannada(text) or kannada_call else default


def build_vad() -> SileroVADAnalyzer:
    return SileroVADAnalyzer(params=VADParams(confidence=VAD_CONFIDENCE, min_volume=VAD_MIN_VOLUME,
                                              start_secs=VAD_START_SECS, stop_secs=VAD_STOP_SECS))


class RecordingGroqSTT(GroqSTTService):
    """Groq Whisper that attaches each segment's WAV to its transcript, so the turn's audio can be played back. With several
    languages enabled it leaves the language to Whisper and takes the prompt from the call's language."""

    def __init__(self, *, call_language: CallLanguage | None = None, **kwargs):
        super().__init__(**kwargs)
        self.call_language = call_language or CallLanguage()

    async def _transcribe(self, audio: bytes):
        if not self.call_language.detects:
            return await super()._transcribe(audio)
        # GroqSTTService always sends a language, so detection needs its own request
        kwargs = {"file": ("audio.wav", audio, "audio/wav"), "model": self._settings.model,
                  "response_format": "verbose_json" if self._include_prob_metrics else "json",
                  "prompt": self.call_language.stt_prompt()}
        if self._settings.temperature is not None:
            kwargs["temperature"] = self._settings.temperature
        return await self._client.audio.transcriptions.create(**kwargs)

    async def run_stt(self, audio: bytes):
        async for frame in super().run_stt(audio):
            if isinstance(frame, TranscriptionFrame):
                frame.audio_wav = audio
                self.call_language.heard(keep_transcript(frame))
            yield frame


def build_stt(settings, call_language: CallLanguage | None = None) -> GroqSTTService:
    call_language = call_language or CallLanguage(settings.voice_languages)
    # verbose_json gives per-segment confidence, so keep_transcript can drop what the model made up from noise
    return RecordingGroqSTT(api_key=settings.groq_api_key, include_prob_metrics=True, call_language=call_language,
                            settings=GroqSTTService.Settings(model=settings.stt_model, prompt=call_language.stt_prompt(),
                                                             language=Language(call_language.stt_language() or LANGUAGE)))


def is_phantom(text: str) -> bool:
    words = _PUNCT.sub("", text).strip().lower()
    return not words or words in PHANTOMS


def is_invented_segment(segment: dict) -> bool:
    """A Whisper segment the model itself flags as probably not speech, or one that is only a known phantom phrase."""
    return (segment.get("no_speech_prob", 0.0) > NO_SPEECH_PROB_MAX or segment.get("avg_logprob", 0.0) < AVG_LOGPROB_MIN
            or is_phantom(segment.get("text", "")))


def _segments(result) -> list[dict]:
    segs = getattr(result, "segments", None) if result is not None else None
    if segs is None and isinstance(result, dict):
        segs = result.get("segments")
    out = []
    for s in segs or []:
        out.append(s if isinstance(s, dict) else {k: getattr(s, k, None) for k in ("text", "no_speech_prob", "avg_logprob")})
    return out


def keep_transcript(frame: TranscriptionFrame) -> str | None:
    """The caller's words with noise removed: segments Whisper rates as unlikely speech, and phantom phrases, are dropped."""
    segments = _segments(getattr(frame, "result", None))
    if segments:
        text = " ".join((s.get("text") or "").strip() for s in segments if not is_invented_segment(s)).strip()
    else:
        text = (frame.text or "").strip()
    return None if is_phantom(text) else normalise_refs(text)
