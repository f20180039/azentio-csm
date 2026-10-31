"""Spoken forms. spoken_inr writes an amount in words for the *_spoken tool fields; speakable turns a reply's written
references and mobile numbers into the form edge-tts reads well, just before TTS, so the transcript keeps the written form
(SR-40200, ₹12,450, 5 November 2026) and the caller still hears "S R, 4 0 2 0 0"."""
import re

from .identity import MOBILE_FIRST_DIGITS, MOBILE_LEN
from .speech import REF_PREFIXES

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _below_100(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")


def spoken_inr(n: int) -> str:
    if n == 0:
        return "zero rupees"
    parts = []
    crore, lakh, thousand = n // 10_000_000, (n // 100_000) % 100, (n // 1_000) % 100
    if crore:
        parts.append(f"{spoken_inr(crore)[:-len(' rupees')]} crore")
    if lakh:
        parts.append(f"{_below_100(lakh)} lakh")
    if thousand:
        parts.append(f"{_below_100(thousand)} thousand")
    if (n // 100) % 10:
        parts.append(f"{_ONES[(n // 100) % 10]} hundred")
    if n % 100:
        parts.append(("and " if parts else "") + _below_100(n % 100))
    return " ".join(parts) + " rupees"


HYPHENS = "-\u2010\u2011\u2012\u2013\u2014"  # the model sometimes writes a reference with a non-breaking (U+2011), en (U+2013) or em (U+2014) dash
MOBILE_GROUP = 5  # a 10-digit mobile is read in two groups of five: "9 8 7 6 5, 0 0 0 0 2"
_REFERENCE = re.compile(r"\b(" + "|".join(REF_PREFIXES) + r")[" + HYPHENS + r"](\d+)\b", re.I)
_MOBILE = re.compile(rf"\b([{MOBILE_FIRST_DIGITS}]\d{{{MOBILE_GROUP - 1}}}) ?(\d{{{MOBILE_LEN - MOBILE_GROUP}}})\b")


def _spaced(s: str) -> str:
    return " ".join(s)


def speakable(text: str) -> str:
    """The text as the voice should read it: a known reference (SR-40200) as its letters then its digits, "S R, 4 0 2 0 0";
    a 10-digit mobile (98765 00002 or 9876500002) as "9 8 7 6 5, 0 0 0 0 2". Amounts, dates, plain numbers and unknown
    codes are left as written; edge-tts reads "₹12,450" and "5 November 2026" naturally."""
    if not text:
        return text
    text = _REFERENCE.sub(lambda m: f"{_spaced(m.group(1).upper())}, {_spaced(m.group(2))}", text)
    return _MOBILE.sub(lambda m: f"{_spaced(m.group(1))}, {_spaced(m.group(2))}", text)
