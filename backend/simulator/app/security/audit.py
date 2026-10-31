"""Cryptographic tamper-evident audit ledger with SHA-256 hash chaining."""
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any

GENESIS_HASH = "0" * 64


@dataclass
class AuditEntry:
    id: int
    actor: str
    action: str
    entity_ref: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str
    timestamp: float


class AuditLedger:
    def __init__(self):
        self._entries: list[AuditEntry] = []

    def record(self, actor: str, action: str, entity_ref: str, payload: dict[str, Any]) -> AuditEntry:
        prev_hash = self._entries[-1].hash if self._entries else GENESIS_HASH
        timestamp = time.time()
        entry_id = len(self._entries) + 1

        payload_serialized = json.dumps(payload, sort_keys=True)
        raw_to_hash = f"{prev_hash}|{actor}|{action}|{entity_ref}|{payload_serialized}|{timestamp}"
        entry_hash = hashlib.sha256(raw_to_hash.encode("utf-8")).hexdigest()

        entry = AuditEntry(
            id=entry_id,
            actor=actor,
            action=action,
            entity_ref=entity_ref,
            payload=payload,
            prev_hash=prev_hash,
            hash=entry_hash,
            timestamp=timestamp,
        )
        self._entries.append(entry)
        return entry

    def verify_integrity(self) -> tuple[bool, int | None]:
        """Validates the entire chain. Returns (is_valid, first_broken_index)."""
        expected_prev = GENESIS_HASH
        for idx, entry in enumerate(self._entries):
            if entry.prev_hash != expected_prev:
                return False, idx

            payload_serialized = json.dumps(entry.payload, sort_keys=True)
            raw = f"{entry.prev_hash}|{entry.actor}|{entry.action}|{entry.entity_ref}|{payload_serialized}|{entry.timestamp}"
            recomputed = hashlib.sha256(raw.encode("utf-8")).hexdigest()

            if recomputed != entry.hash:
                return False, idx
            expected_prev = entry.hash

        return True, None

    def get_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        return [asdict(e) for e in reversed(self._entries[-limit:])]


# Global in-memory audit ledger instance
audit_ledger = AuditLedger()
