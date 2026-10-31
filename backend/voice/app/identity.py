"""What the caller said about who they are, read from the transcript: the mobile number and date of birth that verification
uses, so the bank is asked about the caller's own words and never about digits a language model copied wrongly or invented.

Texts arrive after speech normalisation (`normalise_spoken_digits` / `normalise_refs`), so "double five" is already "55"
and Kannada numerals are ASCII; both are applied again here, harmlessly, for texts that come another way."""
import re
from datetime import date

from .speech import _DIGIT_WORDS, KANNADA_DIGITS, normalise_spoken_digits

MOBILE_LEN = 10
COUNTRY_CODE = "91"
TRUNK_PREFIX = "0"
MOBILE_FIRST_DIGITS = "6789"  # Indian mobiles
MIN_BIRTH_YEARS, MAX_BIRTH_YEARS = 10, 120  # a date of birth this many years before today
MOBILE_ATTEMPT_MIN, MOBILE_ATTEMPT_MAX = 7, 13  # a digit run this long that is not 10 digits was an attempt at a mobile number

HOMOPHONES = frozenset({"to", "too", "for", "ate"})  # digits inside a reference, plain words in a sentence: not counted here
_WORD_DIGITS = {w: d for w, d in _DIGIT_WORDS.items() if w not in HOMOPHONES}
_DIGIT_TOKEN = r"(?:\d+|" + "|".join(sorted(_WORD_DIGITS, key=len, reverse=True)) + r")"
_DIGIT_GROUP = re.compile(r"(?<!\w)\+?" + _DIGIT_TOKEN + r"(?:[\s-]+" + _DIGIT_TOKEN + r")*(?!\w)", re.I)
_NUMERIC_DATE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b")

_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
_MONTHS = {name: i for i, name in enumerate(_MONTH_NAMES, 1)} | {name[:3]: i for i, name in enumerate(_MONTH_NAMES, 1)} | {"sept": 9}
_MONTH = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?,?"
_ORDINAL_SUFFIX = r"(?:st|nd|rd|th)?"

_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
          "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_CENTURIES = {"eighteen": 1800, "nineteen": 1900, "twenty": 2000}
_ORDINAL_UNITS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9}
_ORDINAL_TEENS = {"tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
                  "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30}
_ORDINALS = {**_ORDINAL_UNITS, **_ORDINAL_TEENS,
             **{f"{tens} {unit}": _TENS[tens] + n for tens in ("twenty", "thirty") for unit, n in _ORDINAL_UNITS.items() if _TENS[tens] + n <= 31}}
_ORDINAL_ALT = "|".join(sorted(_ORDINALS, key=len, reverse=True)).replace(" ", r"[\s-]+")
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ORDINAL_BEFORE_MONTH = re.compile(rf"\b({_ORDINAL_ALT})\b(?=\s+(?:of\s+)?(?:{_MONTH_ALT})\b)", re.I)  # 'third of November'
_ORDINAL_AFTER_MONTH = re.compile(rf"\b((?:{_MONTH_ALT})\s+)({_ORDINAL_ALT})\b", re.I)  # 'November third'
_REFERENCE = re.compile(r"\b[A-Za-z]{2,4}-\d+\b")  # PL-31002, SR-40102, TXN-88213, CUST-1002
_AMOUNT = re.compile(r"(?:₹|\brs\.?|\brupees)\s*\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s*(?:rupees|rs|lakhs?|crores?|thousand|k)\b"
                     r"|\b\d{1,3}(?:,\d{2,3})+\b", re.I)  # Rs 9800, 6 lakh, 12,450, 1,00,000
SMALL_NUMBER_DIGITS = 2  # a leftover run this short (a count, a day, 'Question 0') is not an identity detail


def _alt(words) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


_SEP = r"[\s-]+"
_UNDER_HUNDRED = rf"(?:{_alt(_TEENS)}|(?:{_alt(_TENS)})(?:{_SEP}(?:{_alt(_UNITS)}))?|{_alt(_UNITS)})"
_CENTURY_YEAR = re.compile(rf"\b(?P<century>{_alt(_CENTURIES)}){_SEP}"
                           rf"(?P<rest>hundred(?:{_SEP}and)?(?:{_SEP}{_UNDER_HUNDRED})?|oh{_SEP}(?:{_alt(_UNITS)})|{_UNDER_HUNDRED})\b", re.I)
_THOUSAND_YEAR = re.compile(rf"\btwo{_SEP}thousand(?P<rest>(?:{_SEP}and)?{_SEP}{_UNDER_HUNDRED})?\b", re.I)

_ISO = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b")
_DAY_FIRST = re.compile(r"\b(?P<d>\d{1,2})[/-](?P<m>\d{1,2})[/-](?P<y>\d{4})\b")
_DAY_MONTH_YEAR = re.compile(rf"\b(?P<d>\d{{1,2}}){_ORDINAL_SUFFIX}\s+(?:of\s+)?{_MONTH.replace('(', '(?P<m>', 1)}\s+(?P<y>\d{{4}})\b", re.I)
_MONTH_DAY_YEAR = re.compile(rf"\b{_MONTH.replace('(', '(?P<m>', 1)}\s+(?P<d>\d{{1,2}}){_ORDINAL_SUFFIX},?\s+(?P<y>\d{{4}})\b", re.I)
_SHORT_YEAR_DATE = re.compile(rf"\b(?:\d{{1,2}}{_ORDINAL_SUFFIX}\s+(?:of\s+)?{_MONTH}|{_MONTH}\s+\d{{1,2}}{_ORDINAL_SUFFIX},?)\s+'?\d{{2}}\b", re.I)  # '3 Nov 85'


def _prepare(text: str) -> str:
    return normalise_spoken_digits((text or "").translate(KANNADA_DIGITS))


def _converted(text: str) -> str:
    """The turn with spoken digits expanded, Kannada numerals, ordinal days and spoken years as numbers."""
    return _words_to_numbers(_prepare(text))


def _blank_dates(converted: str) -> str:
    """Dates taken out, so '3 November 1985' never lends its digits to a mobile number said next to it."""
    for pattern in (_NUMERIC_DATE, _DAY_MONTH_YEAR, _MONTH_DAY_YEAR):
        converted = pattern.sub(" ", converted)
    return converted


def _groups_in(blanked: str) -> list[str]:
    out = []
    for m in _DIGIT_GROUP.finditer(blanked):
        tokens = re.split(r"[\s-]+", m.group(0).lstrip("+"))
        out.append("".join(t if t.isdigit() else _WORD_DIGITS[t.lower()] for t in tokens if t))
    return out


def _groups(text: str) -> list[str]:
    """Every run of digits the caller said, as digit strings: '98765 00002' and 'nine eight seven…' alike; dates left out."""
    return _groups_in(_blank_dates(_converted(text)))


def is_mobile_attempt(run: str) -> bool:
    """A run of digits that was meant as a mobile number but is not 10 digits long."""
    return MOBILE_ATTEMPT_MIN <= len(run) <= MOBILE_ATTEMPT_MAX and len(run) != MOBILE_LEN


def _without_prefix(d: str) -> str:
    if len(d) > MOBILE_LEN and d.startswith(COUNTRY_CODE):
        return d[len(COUNTRY_CODE):]
    if len(d) > MOBILE_LEN and d.startswith(TRUNK_PREFIX):
        return d[len(TRUNK_PREFIX):]
    return d


def _mobile_in(d: str) -> str | None:
    d = _without_prefix(d)
    if len(d) < MOBILE_LEN:
        return None
    if len(d) % MOBILE_LEN == 0:  # two numbers said back to back ('…00002 93809 39280'): the last one is the correction
        chunks = [d[i:i + MOBILE_LEN] for i in range(0, len(d), MOBILE_LEN)]
        if all(c[0] in MOBILE_FIRST_DIGITS for c in chunks):
            return chunks[-1]
    for i in range(len(d) - MOBILE_LEN + 1):  # a stray digit may have joined the run ('…00002 3 November'): the first good window
        if (window := d[i:i + MOBILE_LEN])[0] in MOBILE_FIRST_DIGITS:
            return window
    return None


def clean_mobile(raw: str) -> str | None:
    """A 10-digit Indian mobile from a model's or form's value ('+91 98765 00002'), or None when it is not exactly that."""
    d = _without_prefix("".join(c for c in str(raw or "") if c.isdigit()))
    return d if len(d) == MOBILE_LEN and d[0] in MOBILE_FIRST_DIGITS else None


def extract_mobile(text: str) -> str | None:
    """The last Indian mobile number said in the text, as 10 ASCII digits; None when none was said."""
    found = [m for g in _groups(text) if (m := _mobile_in(g))]
    return found[-1] if found else None


def digit_run(text: str) -> str | None:
    """The longest run of digits said (country code and trunk zero dropped), to show a short or long attempt at a mobile number."""
    runs = [_without_prefix(g) for g in _groups(text)]
    return max(reversed(runs), key=len) if runs else None


def _words_to_numbers(text: str) -> str:
    def year(m: re.Match) -> str:
        base = _CENTURIES.get((m.groupdict().get("century") or "").lower(), 2000)
        words = re.split(r"[\s-]+", (m.group("rest") or "").lower())  # 'hundred', 'and', 'oh' add nothing
        return str(base + sum(_TEENS.get(w, 0) + _TENS.get(w, 0) + _UNITS.get(w, 0) for w in words))

    def ordinal(word: str) -> str:
        return str(_ORDINALS[re.sub(r"[\s-]+", " ", word.lower())])

    text = _CENTURY_YEAR.sub(year, _THOUSAND_YEAR.sub(year, text))
    text = _ORDINAL_BEFORE_MONTH.sub(lambda m: ordinal(m.group(1)), text)
    return _ORDINAL_AFTER_MONTH.sub(lambda m: m.group(1) + ordinal(m.group(2)), text)


def _birth_date(y: int, m: int, d: int, today: date) -> str | None:
    if not (today.year - MAX_BIRTH_YEARS <= y <= today.year - MIN_BIRTH_YEARS):
        return None
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def clean_dob(raw: str, today: date) -> str | None:
    """An ISO date of birth from a model's value, only when it is a real date 10-120 years before today."""
    if not (m := _ISO.fullmatch(str(raw or "").strip())):
        return None
    return _birth_date(int(m["y"]), int(m["m"]), int(m["d"]), today)


def extract_dob(text: str, today: date) -> str | None:
    """The last date of birth said in the text as YYYY-MM-DD: numeric, 'third of November 1985', 'Nov 3, 1985' or words for
    the year ('nineteen eighty-five', 'two thousand and five'); None when no plausible birth date was said."""
    text = _converted(text)
    found: list[tuple[int, str]] = []
    for pattern in (_ISO, _DAY_FIRST, _DAY_MONTH_YEAR, _MONTH_DAY_YEAR):
        for m in pattern.finditer(text):
            month = m["m"]
            month_n = _MONTHS[month.lower()] if not month.isdigit() else int(month)
            day, year = int(m["d"]), int(m["y"])
            iso = _birth_date(year, month_n, day, today)
            if iso is None and pattern is _DAY_FIRST and month_n <= 31 and day <= 12:  # '11/03/1985' said month first
                iso = _birth_date(year, day, month_n, today)
            if iso:
                found.append((m.start(), iso))
    return max(found)[1] if found else None


def unexplained_numbers(text: str) -> bool:
    """Whether the turn carried numbers this code could not read, so the model may have heard a detail it did not: letters
    outside the Latin scripts (Kannada or Hindi number words), a date with a two-digit year ('3 Nov 85'), or a digit run of
    three or more left over once the mobile number, the dates, a wrong-length attempt at the mobile, bank references
    (PL-31002) and amounts (Rs 9800, 6 lakh, 12,450) are taken out. A turn fully accounted for gives the model nothing to add."""
    converted = _converted(text)
    if any(ch.isalpha() and ord(ch) > 0x024F for ch in converted):
        return True
    if _SHORT_YEAR_DATE.search(converted):
        return True
    groups = _groups_in(_AMOUNT.sub(" ", _REFERENCE.sub(" ", _blank_dates(converted))))
    if any(_mobile_in(g) for g in groups):
        groups = [g for g in groups if _mobile_in(g) is None]
    elif groups and is_mobile_attempt(_without_prefix(longest := max(reversed(groups), key=len))):
        groups.remove(longest)
    return any(len(g) > SMALL_NUMBER_DIGITS for g in groups)
