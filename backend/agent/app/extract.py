import hashlib
import json
import logging
import time

from pydantic import ValidationError

from .config import Settings
from .jsonout import StructuredResult, complete_structured
from .llm.gateway import Gateway, LlmResponse
from .logs import log
from .pdf import ParsedPdf, parse
from .schemas import Schema
from .security import pii, spotlight
from .security.injection import detector

logger = logging.getLogger("agent.extract")


def extract(data: bytes, schema: Schema, gateway: Gateway, settings: Settings) -> dict:
    started = time.perf_counter()
    parsed = parse(data, settings.max_pages)

    # Injection is scored over everything, hidden text included: hidden text is
    # the usual carrier.
    all_text = "\n".join([p["text"] for p in parsed.pages] + [h.text for h in parsed.hidden])
    injection = detector.score(all_text)

    totals = {name: 0 for name in pii.PII_TYPES}
    pages = []
    for page in parsed.pages:
        masked, counts = pii.mask(page["text"])
        pages.append({"page": page["page"], "text": masked})
        for name, n in counts.items():
            totals[name] += n
    hidden = [
        {"page": h.page, "text": pii.mask(h.text)[0], "reason": h.reason} for h in parsed.hidden
    ]

    result, path = _template(schema, pages, parsed), "template"
    if result is None:
        result, path = _model(schema, pages, gateway), "llm"
    last = result.responses[-1]
    response = {
        "page_count": parsed.page_count,
        "pages": pages,
        "fields": result.value.model_dump(mode="json") if result.value else {},
        "extraction_error": result.error,
        "extraction_path": path,
        "document": parsed.meta,
        "security": {
            "hidden_text": hidden,
            "injection": {"suspected": injection.suspected, "score": injection.score, "matches": injection.matches},
            "pii": {"masked": totals},
        },
        "model": {"provider": last.provider, "name": last.model, "prompt_version": schema.prompt_version},
        "usage": {
            "input_tokens": sum(r.input_tokens for r in result.responses),
            "output_tokens": sum(r.output_tokens for r in result.responses),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    }
    log(
        logger,
        "extracted",
        sha256=hashlib.sha256(data).hexdigest(),
        schema=schema.key,
        pages=parsed.page_count,
        hidden_spans=len(hidden),
        injection_score=injection.score,
        pii_masked=sum(totals.values()),
        provider=last.provider,
        path=path,
        valid=result.error is None,
        latency_ms=response["usage"]["latency_ms"],
    )
    return response


def _template(schema: Schema, pages: list[dict], parsed: ParsedPdf) -> StructuredResult | None:
    """Known layouts are parsed in code: exact, free, and nothing for an injected instruction to steer."""
    if schema.parser is None:
        return None
    fields = schema.parser(pages, parsed)
    if fields is None:
        return None
    try:
        value = schema.model.model_validate(fields)
    except ValidationError as exc:
        log(logger, "template_parse_invalid", schema=schema.key, error=str(exc)[:300])
        return None
    return StructuredResult(value, None, [LlmResponse(text="", provider="template", model=schema.key)])


def _model(schema: Schema, pages: list[dict], gateway: Gateway) -> StructuredResult:
    # Only visible, masked text reaches the model, inside random delimiters.
    tag = spotlight.new_tag()
    document = "\n\n".join(f"--- page {p['page']} ---\n{p['text']}" for p in pages)
    visible_text = "\n".join(p["text"] for p in pages)
    return complete_structured(
        gateway,
        schema.model,
        purpose="extract",
        system=f"{schema.prompt}\n\n{spotlight.system_rule(tag)}",
        user=spotlight.wrap(document, tag),
        mock_response=lambda: json.dumps(schema.mock(visible_text)),
    )
