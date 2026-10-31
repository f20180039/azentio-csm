"""PII redaction and masking engine for banking identifiers."""
import re
from typing import NamedTuple

# Regular expressions for Indian BFSI identifiers
CARD_REGEX = re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")
AADHAAR_REGEX = re.compile(r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b")
PAN_REGEX = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE)
PHONE_REGEX = re.compile(r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b")
CVV_REGEX = re.compile(r"\b(?:cvv|cvc)[:\s]*([0-9]{3,4})\b", re.IGNORECASE)


class RedactionResult(NamedTuple):
    redacted_text: str
    tokens_masked: dict[str, str]
    pii_detected: bool


class PIIRedactor:
    """Masks customer PII before sending text to external LLMs or logs."""

    @classmethod
    def redact(cls, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(redacted_text="", tokens_masked={}, pii_detected=False)

        masked_tokens: dict[str, str] = {}
        cleaned = text

        # 1. Mask CVV immediately
        def _mask_cvv(match: re.Match) -> str:
            raw = match.group(0)
            masked_tokens[raw] = "[CVV_REDACTED]"
            return "CVV [REDACTED]"
        cleaned = CVV_REGEX.sub(_mask_cvv, cleaned)

        # 2. Mask Card Numbers (show only last 4)
        def _mask_card(match: re.Match) -> str:
            raw = match.group(0)
            digits = re.sub(r"\D", "", raw)
            token = f"[CARD_***_{digits[-4:]}]"
            masked_tokens[token] = raw
            return token
        cleaned = CARD_REGEX.sub(_mask_card, cleaned)

        # 3. Mask Aadhaar
        def _mask_aadhaar(match: re.Match) -> str:
            raw = match.group(0)
            digits = re.sub(r"\D", "", raw)
            token = f"[AADHAAR_***_{digits[-4:]}]"
            masked_tokens[token] = raw
            return token
        cleaned = AADHAAR_REGEX.sub(_mask_aadhaar, cleaned)

        # 4. Mask PAN
        def _mask_pan(match: re.Match) -> str:
            raw = match.group(0).upper()
            token = f"[PAN_{raw[:2]}***{raw[-2:]}]"
            masked_tokens[token] = raw
            return token
        cleaned = PAN_REGEX.sub(_mask_pan, cleaned)

        # 5. Mask Phone Numbers
        def _mask_phone(match: re.Match) -> str:
            raw = match.group(0)
            digits = re.sub(r"\D", "", raw)[-10:]
            token = f"[PHONE_***_{digits[-4:]}]"
            masked_tokens[token] = raw
            return token
        cleaned = PHONE_REGEX.sub(_mask_phone, cleaned)

        return RedactionResult(
            redacted_text=cleaned,
            tokens_masked=masked_tokens,
            pii_detected=len(masked_tokens) > 0
        )
