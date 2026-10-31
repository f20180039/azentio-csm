import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .jsonout import complete_structured
from .llm.gateway import Gateway
from .quotes import contains
from .security import pii, spotlight


class Evidence(BaseModel):
    page: int
    quote: str


class FindingIn(BaseModel):
    id: str
    rule_id: str
    title: str
    detail: str = ""
    evidence: list[Evidence] = []


class PageIn(BaseModel):
    document_id: str
    page: int
    text: str


class ExplainRequest(BaseModel):
    case_type: str
    findings: list[FindingIn]
    pages: list[PageIn]


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    page: int
    text: str


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_id: str
    note: str
    quotes: list[Quote] = Field(default_factory=list)


class ExplainOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = ""
    notes: list[Note]

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_note(cls, data: object) -> object:
        # Small local models sometimes return one note instead of the wrapper.
        if isinstance(data, dict) and "finding_id" in data and "notes" not in data:
            return {"summary": "", "notes": [data]}
        return data


SYSTEM = (
    "You help an insurance or banking reviewer understand automated findings. "
    "For each finding, write one or two plain sentences saying what the evidence shows and why it matters. "
    "Support every note with one or more quotes copied exactly, character for character, from the document pages, "
    "and give the document_id and page each quote came from. Never invent a quote. "
    "If the pages do not support a finding, say so in the note and give no quotes. "
    "summary: two sentences for the whole case."
)
PROMPT_VERSION = "explain-v1"


def _mock(req: ExplainRequest, pages: list[PageIn]) -> str:
    notes = []
    for f in req.findings:
        quotes = []
        for ev in f.evidence:
            page = next((p for p in pages if p.page == ev.page and contains(p.text, ev.quote)), None)
            if page:
                quotes.append({"document_id": page.document_id, "page": page.page, "text": ev.quote})
        notes.append({"finding_id": f.id, "note": f"{f.title}. {f.detail}".strip(), "quotes": quotes})
    summary = f"{len(req.findings)} finding(s) for this {req.case_type} case."
    return json.dumps({"summary": summary, "notes": notes})


def _locate(quote: Quote, pages: list[PageIn]) -> Quote | None:
    """Accept the quote on its cited page, or on another page if the model mis-cited it."""
    cited = [p for p in pages if p.document_id == quote.document_id and p.page == quote.page]
    for page in cited + [p for p in pages if p not in cited]:
        if contains(page.text, quote.text):
            return Quote(document_id=page.document_id, page=page.page, text=quote.text)
    return None


def explain(req: ExplainRequest, gateway: Gateway) -> dict:
    pages = [p.model_copy(update={"text": pii.mask(p.text)[0]}) for p in req.pages]
    known_ids = {f.id for f in req.findings}

    tag = spotlight.new_tag()
    document = "\n\n".join(f"--- document_id={p.document_id} page={p.page} ---\n{p.text}" for p in pages)
    findings = json.dumps([f.model_dump() for f in req.findings], ensure_ascii=False)
    user = f"Findings:\n{findings}\n\nDocument pages:\n{spotlight.wrap(document, tag)}"

    result = complete_structured(
        gateway,
        ExplainOutput,
        purpose="explain",
        system=f"{SYSTEM}\n\n{spotlight.system_rule(tag)}",
        user=user,
        mock_response=lambda: _mock(req, pages),
    )
    last = result.responses[-1]
    notes, dropped = [], []
    if result.value is None:
        dropped = [{"finding_id": f.id, "reason": "invalid_model_output"} for f in req.findings]
        summary = ""
    else:
        summary = result.value.summary
        for note in result.value.notes:
            if note.finding_id not in known_ids:
                dropped.append({"finding_id": note.finding_id, "reason": "unknown_finding"})
                continue
            if not note.quotes:
                dropped.append({"finding_id": note.finding_id, "reason": "no_quote"})
                continue
            located = [_locate(q, pages) for q in note.quotes]
            if any(q is None for q in located):
                dropped.append({"finding_id": note.finding_id, "reason": "quote_not_found"})
                continue
            notes.append({"finding_id": note.finding_id, "note": note.note, "quotes": [q.model_dump() for q in located]})
    return {
        "summary": summary,
        "notes": notes,
        "dropped": dropped,
        "model": {"provider": last.provider, "name": last.model, "prompt_version": PROMPT_VERSION},
        "usage": {
            "input_tokens": sum(r.input_tokens for r in result.responses),
            "output_tokens": sum(r.output_tokens for r in result.responses),
            "latency_ms": sum(r.latency_ms for r in result.responses),
        },
    }
