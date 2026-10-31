"""Parse model output into a validated Pydantic object, with one repair retry."""
import json
import re
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, ValidationError

from .llm.gateway import Gateway, LlmRequest, LlmResponse

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class OutputError(ValueError):
    pass


def parse_json_object(text: str) -> dict:
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise OutputError("no JSON object in model output")
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise OutputError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise OutputError("model output is not a JSON object")
    return value


def validate(model: type[BaseModel], text: str) -> BaseModel:
    try:
        return model.model_validate(parse_json_object(text))
    except ValidationError as exc:
        raise OutputError(f"schema validation failed: {exc.errors(include_url=False)}") from exc


@dataclass
class StructuredResult:
    value: BaseModel | None
    error: str | None
    responses: list[LlmResponse] = field(default_factory=list)


def complete_structured(
    gateway: Gateway,
    model: type[BaseModel],
    purpose: str,
    system: str,
    user: str,
    mock_response: Callable[[], str],
) -> StructuredResult:
    schema = json.dumps(model.model_json_schema(), sort_keys=True)
    system = f"{system}\n\nReturn only one JSON object that validates against this JSON Schema:\n{schema}"
    responses: list[LlmResponse] = []

    resp = gateway.complete(LlmRequest(purpose, system, user, mock_response))
    responses.append(resp)
    try:
        return StructuredResult(validate(model, resp.text), None, responses)
    except OutputError as first:
        repair = (
            f"{user}\n\nYour previous answer was:\n{resp.text}\n\n"
            f"It was rejected: {first}. Return only the corrected JSON object."
        )
        resp = gateway.complete(LlmRequest(purpose, system, repair, mock_response))
        responses.append(resp)
        try:
            return StructuredResult(validate(model, resp.text), None, responses)
        except OutputError as second:
            return StructuredResult(None, str(second), responses)
