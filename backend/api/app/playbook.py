"""The renewal playbook: every limit the voice agent works within, loaded and validated at start."""
from dataclasses import dataclass
from pathlib import Path

import yaml


class InvalidPlaybook(ValueError):
    pass


@dataclass(frozen=True)
class Playbook:
    id: str
    version: int
    greeting: str
    max_discount_percent: int
    payment_plans: tuple[str, ...]
    removable_optional_addons: bool
    max_out_of_playbook_requests: int
    max_verify_failures: int


_FIELDS = {"id", "version", "greeting", "maxDiscountPercent", "paymentPlans", "removableOptionalAddons",
           "maxOutOfPlaybookRequests", "maxVerifyFailures"}


def load_playbook(path: str | Path) -> Playbook:
    src = str(path)
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise InvalidPlaybook(f"{src}: cannot read playbook ({e})") from e
    if not isinstance(raw, dict):
        raise InvalidPlaybook(f"{src}: id is required")
    unknown = set(raw) - _FIELDS
    if unknown:
        raise InvalidPlaybook(f"{src}: unknown fields {sorted(unknown)}")

    def required(field: str):
        value = raw.get(field)
        if value is None or (isinstance(value, (str, list)) and not value):
            raise InvalidPlaybook(f"{src}: {field} is required")
        return value

    def non_negative(field: str) -> int:
        value = required(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidPlaybook(f"{src}: {field} must be an integer")
        if value < 0:
            raise InvalidPlaybook(f"{src}: {field} must not be negative")
        return value

    pid, greeting, plans = required("id"), required("greeting"), required("paymentPlans")
    version = non_negative("version")
    discount = non_negative("maxDiscountPercent")
    out_of = non_negative("maxOutOfPlaybookRequests")
    verify = non_negative("maxVerifyFailures")
    if discount > 100:
        raise InvalidPlaybook(f"{src}: maxDiscountPercent must be at most 100")
    removable = raw.get("removableOptionalAddons")
    if not isinstance(removable, bool):
        raise InvalidPlaybook(f"{src}: removableOptionalAddons is required")
    return Playbook(str(pid), version, str(greeting), discount, tuple(str(p) for p in plans), removable, out_of,
                    verify)
