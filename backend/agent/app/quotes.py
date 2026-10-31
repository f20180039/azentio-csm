"""Quote verification: a quote counts only if it appears in the source page."""
import re

_SPACE = re.compile(r"\s+")
_CHARS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


def normalise(text: str) -> str:
    return _SPACE.sub(" ", text.translate(_CHARS)).strip().casefold()


def contains(page_text: str, quote: str) -> bool:
    needle = normalise(quote)
    return bool(needle) and needle in normalise(page_text)
