"""Masks Indian personal identifiers before text reaches an LLM or leaves the service.
IFSC codes identify a bank branch, not a person, so they are kept."""
import re

# (type, pattern, replacement). Order matters: specific patterns run before the
# generic digit run. A bare 12-digit number is treated as an account number
# unless it is grouped 4-4-4 or labelled Aadhaar.
_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "[PAN]"),
    ("AADHAAR", re.compile(r"\b[2-9][0-9]{3}[ -][0-9]{4}[ -][0-9]{4}\b"), "[AADHAAR]"),
    ("AADHAAR", re.compile(r"(?i)\b((?:aadhaar|aadhar|uid)(?: no\.?| number)?\s*[:#-]?\s*)[2-9][0-9]{11}\b"), r"\1[AADHAAR]"),
    ("PHONE", re.compile(r"(?<![\w])(?:\+91[ -]?|0)?[6-9][0-9]{4}[ -]?[0-9]{5}\b"), "[PHONE]"),
    ("ACCOUNT", re.compile(r"\b[0-9]{9,18}\b"), "[ACCOUNT]"),
]
PII_TYPES = list(dict.fromkeys(name for name, _, _ in _RULES))


def mask(text: str) -> tuple[str, dict[str, int]]:
    counts = {name: 0 for name in PII_TYPES}
    for name, pattern, replacement in _RULES:
        text, n = pattern.subn(replacement, text)
        counts[name] += n
    return text, counts
