"""Schema registry. A schema = a Pydantic model + an extraction prompt + a
deterministic mock. Topic packs add a module here and register it."""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel

if TYPE_CHECKING:
    from ..pdf import ParsedPdf


@dataclass(frozen=True)
class Schema:
    key: str
    model: type[BaseModel]
    prompt: str
    prompt_version: str
    mock: Callable[[str], dict]  # text -> fields, used by the mock provider
    # Deterministic parser for known layouts, tried before any model. Gets masked pages plus the parsed PDF
    # (fonts, metadata); returns fields, or None when it does not recognise the layout.
    parser: "Callable[[list[dict], ParsedPdf], dict | None] | None" = None


REGISTRY: dict[str, Schema] = {}


def register(schema: Schema) -> Schema:
    REGISTRY[schema.key] = schema
    return schema


def get(key: str) -> Schema | None:
    return REGISTRY.get(key)


from . import demo  # noqa: E402,F401  (registers itself)
