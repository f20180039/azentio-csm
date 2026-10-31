import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import Schema, register


_CURRENCY_ALIASES = {"₹": "INR", "RS": "INR", "RS.": "INR", "RUPEES": "INR", "$": "USD"}


class Amount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float
    currency: str = Field(min_length=3, max_length=3)
    context: str

    @field_validator("currency", mode="before")
    @classmethod
    def _iso_code(cls, value: object) -> object:
        # Small local models often answer with a symbol; map the common ones.
        if isinstance(value, str):
            return _CURRENCY_ALIASES.get(value.strip().upper(), value.strip().upper())
        return value


class DemoFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_kind: str
    parties: list[str]
    dates: list[str]
    amounts: list[Amount]


PROMPT = (
    "You extract structured facts from business documents for a compliance reviewer. "
    "document_kind: one short noun such as invoice, bill, statement, letter, receipt. "
    "parties: names of organisations or people the document is from or to. "
    "dates: every date as written in the document. "
    "amounts: every monetary amount with its ISO currency code (INR for ₹, Rs, INR) "
    "and the few words of context it appears in. Use only facts present in the document."
)

_AMOUNT = re.compile(r"(?:₹|Rs\.?|INR)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)
_DATE = re.compile(
    r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4})\b"
)
_PARTY = re.compile(r"^(?:From|To|Bill To|Billed To|Customer|Vendor|Payee|Name)\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_KINDS = ["invoice", "statement", "receipt", "bill", "letter", "claim", "policy"]


def mock(text: str) -> dict:
    lowered = text.lower()
    kind = next((k for k in _KINDS if k in lowered), "document")
    amounts = []
    for match in _AMOUNT.finditer(text):
        start = text.rfind("\n", 0, match.start()) + 1
        end = text.find("\n", match.end())
        line = text[start : end if end != -1 else len(text)]
        amounts.append({"value": float(match.group(1).replace(",", "")), "currency": "INR", "context": line.strip()[:120]})
    return {
        "document_kind": kind,
        "parties": list(dict.fromkeys(m.strip() for m in _PARTY.findall(text))),
        "dates": list(dict.fromkeys(_DATE.findall(text))),
        "amounts": amounts,
    }


SCHEMA = register(Schema(key="demo", model=DemoFields, prompt=PROMPT, prompt_version="extract-v1", mock=mock))
