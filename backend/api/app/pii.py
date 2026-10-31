"""PII detection and tokenising for stored transcripts.

`find_pii` spots mobiles, dates of birth, Aadhaar, PAN, e-mail, card and account numbers and spoken digit runs in
free text; `Redactor` walks a turn's text and meta (strings, lists, dicts, including structured name fields),
stores each value in the vault and leaves `[KIND#n]` tokens behind. Bank references (SR-40102, TXN-88213,
CUST-1002), masked numbers (••• 4012), amounts and recent dates such as due dates are kept.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from app.pii_vault import PiiVault, token_for
from app.vocab import PiiKind, RefPrefix

DOB_MIN_AGE_YEARS = 16
NAME_KEYS = frozenset({"first_name", "last_name", "name"})
TOOL_TRACE_KEY = "tool_trace"  # a tool_trace step's `name` is the tool, not a person
MIN_SPOKEN_DIGITS = 6

# When two matches cover the same span, the earlier kind in this order wins.
PRIORITY = {k: i for i, k in enumerate((PiiKind.CARD, PiiKind.AADHAAR, PiiKind.MOBILE, PiiKind.DOB, PiiKind.PAN,
                                        PiiKind.EMAIL, PiiKind.ACCOUNT_NUMBER, PiiKind.DIGITS, PiiKind.NAME))}
NUMERIC_KINDS = frozenset({PiiKind.MOBILE, PiiKind.AADHAAR, PiiKind.CARD, PiiKind.ACCOUNT_NUMBER})
INT_KINDS = frozenset({PiiKind.MOBILE, PiiKind.AADHAAR, PiiKind.CARD})

_MONTHS = {m: i + 1 for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july",
                                            "august", "september", "october", "november", "december"))}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                "seven": "7", "eight": "8", "nine": "9"}
_MULTIPLIER = {"double": 2, "triple": 3}
_WORD = "(?:" + "|".join(_DIGIT_WORDS) + ")"
_UNIT = rf"(?:(?:double|triple)[\s-]+)?{_WORD}"

# Ten digits starting 6-9 with at most one space or hyphen inside, optionally prefixed +91, 91 or 0.
_MOBILE_BODY = "|".join([r"\d{9}"] + [rf"\d{{{k}}}[\s-]\d{{{9 - k}}}" for k in range(0, 9)])
MOBILE_RE = re.compile(rf"(?<![\d])(?:\+?91[\s-]?|0)?([6-9](?:{_MOBILE_BODY}))(?![\d])")
AADHAAR_CONTIGUOUS_RE = re.compile(r"(?<!\d)[2-9]\d{11}(?!\d)")
AADHAAR_GROUPED_RE = re.compile(r"(?<![\d])\d{4}[ -]\d{4}[ -]\d{4}(?![ -]?\d)")
PAN_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Z0-9])")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
CARD_RE = re.compile(r"(?<![\d])\d(?:[ -]?\d){12,18}(?![\d])")
ACCOUNT_RE = re.compile(r"(?<!\d)\d{9,18}(?!\d)")
DIGITS_RE = re.compile(rf"(?<![\w-]){_UNIT}(?:[\s,-]+{_UNIT})+(?![\w-])", re.IGNORECASE)
DATE_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
DATE_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})([/-])(\d{1,2})\2(\d{4})(?!\d)")
DATE_D_MONTH_Y_RE = re.compile(rf"(?<!\w)(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?,?\s+(\d{{4}})(?!\d)",
                               re.IGNORECASE)
DATE_MONTH_D_Y_RE = re.compile(rf"(?<!\w)({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)",
                               re.IGNORECASE)
# SR-40102, TXN-88213, CUST-1002: digits right after a known bank reference prefix are kept. Only these
# uppercase prefixes qualify, so "mobile-9876500002" or "Mob-98765 00002" are still redacted.
REFERENCE_PREFIX_RE = re.compile(r"(?<![A-Za-z])(?:" + "|".join(p.value for p in RefPrefix) + r")-$")
TOKEN_RE = re.compile(r"^\[(?:" + "|".join(k.value for k in PiiKind) + r")#\d+\]$")  # already redacted


@dataclass(frozen=True)
class Found:
    kind: PiiKind
    value: str  # canonical form: digits only, ISO date, the e-mail or name as written
    start: int
    end: int


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _digits(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def _old_enough(d: date, today: date) -> bool:
    """True when `d` is at least DOB_MIN_AGE_YEARS before `today`: a date of birth rather than a due date."""
    try:
        cutoff = today.replace(year=today.year - DOB_MIN_AGE_YEARS)
    except ValueError:  # 29 February
        cutoff = today.replace(year=today.year - DOB_MIN_AGE_YEARS, day=28)
    return d <= cutoff


def _date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _after_reference_prefix(text: str, start: int) -> bool:
    return REFERENCE_PREFIX_RE.search(text, 0, start) is not None


def _candidates(text: str, today: date) -> Iterable[Found]:
    for m in MOBILE_RE.finditer(text):
        yield Found(PiiKind.MOBILE, _digits(m.group(1)), m.start(), m.end())
    for rx in (AADHAAR_CONTIGUOUS_RE, AADHAAR_GROUPED_RE):
        for m in rx.finditer(text):
            yield Found(PiiKind.AADHAAR, _digits(m.group()), m.start(), m.end())
    for m in CARD_RE.finditer(text):
        digits = _digits(m.group())
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            yield Found(PiiKind.CARD, digits, m.start(), m.end())
    for m in ACCOUNT_RE.finditer(text):
        yield Found(PiiKind.ACCOUNT_NUMBER, m.group(), m.start(), m.end())
    for m in PAN_RE.finditer(text):
        yield Found(PiiKind.PAN, m.group(), m.start(), m.end())
    for m in EMAIL_RE.finditer(text):
        yield Found(PiiKind.EMAIL, m.group(), m.start(), m.end())
    for m in DIGITS_RE.finditer(text):
        spoken = _spoken_digits(m.group())
        if len(spoken) >= MIN_SPOKEN_DIGITS:
            yield Found(PiiKind.DIGITS, spoken, m.start(), m.end())
    for m in DATE_ISO_RE.finditer(text):
        yield from _dob(m, _date(int(m.group(1)), int(m.group(2)), int(m.group(3))), today)
    for m in DATE_DMY_RE.finditer(text):
        yield from _dob(m, _date(int(m.group(4)), int(m.group(3)), int(m.group(1))), today)
    for m in DATE_D_MONTH_Y_RE.finditer(text):
        yield from _dob(m, _date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))), today)
    for m in DATE_MONTH_D_Y_RE.finditer(text):
        yield from _dob(m, _date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))), today)


def _dob(m: re.Match, d: date | None, today: date) -> Iterable[Found]:
    if d is not None and _old_enough(d, today):
        yield Found(PiiKind.DOB, d.isoformat(), m.start(), m.end())


def _spoken_digits(phrase: str) -> str:
    out, multiplier = [], 1
    for word in re.split(r"[\s,-]+", phrase.lower()):
        if word in _MULTIPLIER:
            multiplier = _MULTIPLIER[word]
        elif word in _DIGIT_WORDS:
            out.append(_DIGIT_WORDS[word] * multiplier)
            multiplier = 1
    return "".join(out)


def find_pii(text: str, today: date) -> list[Found]:
    """Non-overlapping matches in text order; on overlap the longest wins, then PRIORITY."""
    found = [f for f in _candidates(text, today)
             if not (f.kind in NUMERIC_KINDS and _after_reference_prefix(text, f.start))]
    found.sort(key=lambda f: (f.start, -(f.end - f.start), PRIORITY[f.kind]))
    kept: list[Found] = []
    for f in found:
        if not kept or f.start >= kept[-1].end:
            kept.append(f)
    return kept


def _substitute(text: str, found: list[Found], token: Any) -> str:
    out, pos = [], 0
    for f in found:
        out.append(text[pos:f.start])
        out.append(token(f))
        pos = f.end
    out.append(text[pos:])
    return "".join(out)


def redact_text(text: str, today: date) -> tuple[str, list[Found]]:
    """Stand-alone redaction: tokens numbered per kind in order of first appearance within this text."""
    found = find_pii(text, today)
    tokens: dict[tuple[PiiKind, str], str] = {}
    counts: dict[PiiKind, int] = {}

    def token(f: Found) -> str:
        key = (f.kind, f.value)
        if key not in tokens:
            counts[f.kind] = counts.get(f.kind, 0) + 1
            tokens[key] = token_for(f.kind, counts[f.kind])
        return tokens[key]

    return _substitute(text, found, token), found


class Redactor:
    """Redacts everything written for one call; the same value always maps to the same vault token."""

    def __init__(self, vault: PiiVault, call_id: str, today: date | None = None):
        self.vault = vault
        self.call_id = call_id
        self.today = today or date.today()
        self._tokens: dict[tuple[PiiKind, str], str] = {}

    def token(self, kind: PiiKind, value: str) -> str:
        key = (kind, value)
        if key not in self._tokens:
            self._tokens[key] = self.vault.put(self.call_id, kind, value)
        return self._tokens[key]

    def redact(self, value: Any) -> Any:
        return self._walk(value, ())

    def _walk(self, value: Any, path: tuple) -> Any:
        if isinstance(value, str):
            return self.redact_string(value)
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int):  # a mobile, Aadhaar or card sent as a number; plain counters/epochs stay
            text = str(value)
            found = find_pii(text, self.today)
            if len(found) == 1 and found[0].kind in INT_KINDS and (found[0].start, found[0].end) == (0, len(text)):
                return self.token(found[0].kind, found[0].value)
            return value
        if isinstance(value, list):
            return [self._walk(v, path + (i,)) for i, v in enumerate(value)]
        if isinstance(value, dict):
            return {k: self._field(k, v, path) for k, v in value.items()}
        return value

    def _field(self, key: Any, value: Any, path: tuple) -> Any:
        if (key in NAME_KEYS and isinstance(value, str) and value.strip() and not _is_tool_step(key, path)
                and not TOKEN_RE.match(value.strip())):
            return self.token(PiiKind.NAME, value.strip())
        return self._walk(value, path + (key,))

    def redact_string(self, text: str) -> str:
        found = find_pii(text, self.today)
        if not found:
            return text
        return _substitute(text, found, lambda f: self.token(f.kind, f.value))


def _is_tool_step(key: Any, path: tuple) -> bool:
    return key == "name" and len(path) >= 2 and path[-2] == TOOL_TRACE_KEY and isinstance(path[-1], int)
