"""The speech front end shared by live calls and recorded-audio simulation: voice detection settings, the speech-to-text
service, and the filter that drops transcripts the model invents from noise. Values are tuned from spikes/stt-bench."""
import os
import re
import unicodedata

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
HINDI_PROMPT = "बैंक ग्राहक कॉल। EMI, लोन, खाता, स्टेटमेंट, किस्त, NACH, KYC, SR-40102."
# The prompt once the call is in a script language; the words that keep Whisper in that script while the call is still English
STT_PROMPTS: dict[SpeechLanguage, str] = {SpeechLanguage.KANNADA: KANNADA_PROMPT, SpeechLanguage.HINDI: HINDI_PROMPT}
# ("bank customer call" in that script, the domain words in that script); the English terms (EMI, NACH, KYC...) are said once
_SCRIPT_WORDS: dict[SpeechLanguage, tuple[str, str]] = {
    SpeechLanguage.KANNADA: ("ಬ್ಯಾಂಕ್ ಗ್ರಾಹಕರ ಕರೆ.", "ಸಾಲ, ಲೋನ್, ಖಾತೆ, ಸ್ಟೇಟ್‌ಮೆಂಟ್, ಕಂತು,"),
    SpeechLanguage.HINDI: ("बैंक ग्राहक कॉल।", "लोन, खाता, स्टेटमेंट, किस्त,"),
}
VOICES: dict[SpeechLanguage, str] = {SpeechLanguage.KANNADA: "kn-IN-SapnaNeural", SpeechLanguage.HINDI: "hi-IN-SwaraNeural"}
KANNADA_VOICE = VOICES[SpeechLanguage.KANNADA]
_SCRIPTS: dict[SpeechLanguage, re.Pattern] = {SpeechLanguage.KANNADA: re.compile(r"[ಀ-೿]"), SpeechLanguage.HINDI: re.compile(r"[ऀ-ॿ]")}
# A caller mixing English words into Kannada or Hindi ("मेरा loan statement चाहिए") is still speaking that language: the script
# only has to make up this share of the letters. Vowel signs count as letters, since Indic scripts write most vowels that way.
CODE_MIX_SHARE = 0.3
MOSTLY_SHARE = 0.5  # a reply or fixed line is "mostly" in a script at half its letters
_LETTER = re.compile(r"[^\W\d_]")
_MARK_CATEGORIES = ("Mn", "Mc")


def multilingual_prompt(enabled: tuple[SpeechLanguage, ...]) -> str:
    """The English domain prompt plus the Kannada and/or Hindi words of the enabled languages (BILINGUAL_PROMPT for en,kn).
    Only the en,kn form is benchmarked (docs/stt-benchmark.md); task H2 measures the three-language one."""
    parts = [_SCRIPT_WORDS[lang] for lang in _SCRIPT_WORDS if lang in enabled]
    if not parts:
        return DOMAIN_PROMPT
    headers, words = " ".join(h for h, _ in parts), " ".join(w for _, w in parts)
    return f"Bank customer call. {headers} EMI, {words} NACH, KYC, statement, SR-40102."


MULTILINGUAL_PROMPT = multilingual_prompt((SpeechLanguage.ENGLISH, SpeechLanguage.KANNADA, SpeechLanguage.HINDI))

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


KANNADA_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")
HINDI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
SCRIPT_DIGITS = KANNADA_DIGITS | HINDI_DIGITS


def normalise_refs(text: str) -> str:
    """'S R four zero one zero two' and 'SR for 8213' → 'SR-40102' and 'SR-48213', so ticket and loan references survive accents.
    Kannada (೯೩೮…) and Devanagari (९८७…) numerals become ASCII digits, so a mobile number said in Kannada or Hindi reaches
    verification intact."""
    text = normalise_spoken_digits(text.translate(SCRIPT_DIGITS))
    text = _SPELLED_PREFIX.sub(lambda m: m.group(1).replace(" ", "").upper(), text)

    def fix(m: re.Match) -> str:
        digits = "".join(_DIGIT_WORDS.get(p.lower(), p) for p in re.split(r"[\s.-]+", m.group(2)) if p)
        return f"{m.group(1).upper()}-{digits}" if 4 <= len(digits) <= 8 else m.group(0)
    return _REF.sub(fix, text)


def _letters(text: str | None) -> list[str]:
    """Letters of any script, with Indic vowel signs and other combining marks counted as letters of their script."""
    return [c for c in (text or "") if _LETTER.match(c) or unicodedata.category(c) in _MARK_CATEGORIES]


def _script_shares(text: str | None) -> dict[SpeechLanguage, float]:
    """How much of the text's letters each script language's script makes up; empty when there are no letters."""
    letters = _letters(text)
    if not letters:
        return {}
    return {lang: sum(1 for c in letters if script.match(c)) / len(letters) for lang, script in _SCRIPTS.items()}


def script_language(text: str | None) -> SpeechLanguage | None:
    """KANNADA or HINDI when that script makes up at least CODE_MIX_SHARE of the letters; ENGLISH when there are letters but
    neither script does (Latin, romanised Hindi, Urdu...); None when there are no letters (digits, silence)."""
    shares = _script_shares(text)
    if not shares:
        return None
    lang, share = max(shares.items(), key=lambda item: item[1])
    return lang if share >= CODE_MIX_SHARE else SpeechLanguage.ENGLISH


def is_mostly(language: SpeechLanguage, text: str | None) -> bool:
    """At least half the letters are in the language's script: a reply or fixed line that should get that language's voice."""
    return _script_shares(text).get(language, 0.0) >= MOSTLY_SHARE


def is_mostly_kannada(text: str | None) -> bool:
    return is_mostly(SpeechLanguage.KANNADA, text)


def is_mostly_hindi(text: str | None) -> bool:
    return is_mostly(SpeechLanguage.HINDI, text)


class CallLanguage:
    """The language one call is in: Kannada or Hindi from a transcript in that script until the caller speaks English again."""

    def __init__(self, enabled: tuple[SpeechLanguage, ...] = (SpeechLanguage.ENGLISH,)):
        self.enabled = enabled
        self.current = SpeechLanguage.ENGLISH if SpeechLanguage.ENGLISH in enabled else enabled[0]

    @property
    def detects(self) -> bool:
        """Several languages enabled: Whisper detects the language instead of being pinned to one."""
        return len(self.enabled) > 1

    def heard(self, text: str | None) -> None:
        """Follows the transcript's script, but only into an enabled language: Devanagari on an en,kn call changes nothing."""
        if not self.detects:
            return
        language = script_language(text)
        if language is not None and language in self.enabled:
            self.current = language

    def stt_language(self) -> str | None:
        return None if self.detects else self.enabled[0].value

    def stt_prompt(self) -> str:
        """The current language's prompt once the call is Kannada or Hindi; otherwise the English prompt with the enabled scripts' words."""
        return STT_PROMPTS.get(self.current) or multilingual_prompt(self.enabled)


def voice_for(text: str, default: str, call: CallLanguage | None = None) -> str:
    """The Kannada or Hindi voice for a reply mostly in that script, else for a call in that language; the configured voice otherwise."""
    spoken = next((lang for lang in VOICES if is_mostly(lang, text)), None)
    if spoken is None and call is not None:
        spoken = call.current
    return VOICES.get(spoken, default)


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
