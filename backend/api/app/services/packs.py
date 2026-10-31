"""Rule-pack configuration from resources/packs (configuration, not metrics)."""
from pathlib import Path

import yaml

from app.config import RESOURCES

PACKS_DIR = RESOURCES / "packs"
CORE_PREFIX = "CORE-"


def load_packs(directory: Path = PACKS_DIR) -> list[dict]:
    packs = []
    for path in sorted(directory.glob("*.yml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        routing = raw.get("routing") or {}
        rules = [{"id": rid, "core": rid.startswith(CORE_PREFIX), "weight": r.get("weight"),
                  "rationale": r.get("rationale"), "params": r.get("params")}
                 for rid, r in (raw.get("rules") or {}).items()]
        packs.append({"caseType": raw.get("caseType"), "label": raw.get("label"),
                      "extractionSchema": raw.get("caseType"), "autoClearBelow": routing.get("autoClearBelow"),
                      "escalateAtOrAbove": routing.get("escalateAtOrAbove"), "routing": routing, "rules": rules})
    return sorted(packs, key=lambda p: p["caseType"] or "")
