"""The PII vault: a separate SQLite file holding the values behind `[KIND#n]` transcript tokens.

Each value is encrypted on its own with Fernet under PII_VAULT_KEY. `value_hmac` (HMAC-SHA256 of the call id,
kind and value, keyed with the vault key) lets a repeated value map to its existing token without storing
plaintext. Without a key the vault still issues tokens, so redaction never switches off, but keeps no values;
the HMAC is then keyed with a per-process random secret, so same-value dedupe lasts only for the process.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from cryptography.fernet import Fernet

from app.vocab import PiiKind

SCHEMA = """
CREATE TABLE IF NOT EXISTS pii_values (
    call_id    TEXT NOT NULL,
    token      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    value_hmac TEXT NOT NULL,
    ciphertext BLOB,
    created_at TEXT NOT NULL,
    PRIMARY KEY (call_id, token),
    UNIQUE (call_id, value_hmac)
);
"""


def token_for(kind: PiiKind, n: int) -> str:
    return f"[{kind}#{n}]"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PiiVault:
    def __init__(self, path: Path | str, key: str | None, now: Callable[[], str] | None = None):
        self.path = Path(path)
        self.keyed = bool(key)
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key) if key else None
        self._hmac_key = key.encode() if key else secrets.token_bytes(32)
        self._now = now or _utc_now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(f"BEGIN; {SCHEMA}\nCOMMIT;")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(str(self.path), isolation_level=None, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout = 30000")
        try:
            yield con
        finally:
            con.close()

    def _hmac(self, call_id: str, kind: PiiKind, value: str) -> str:
        material = f"{call_id}|{kind}|{value}".encode("utf-8")
        return hmac.new(self._hmac_key, material, hashlib.sha256).hexdigest()

    def put(self, call_id: str, kind: PiiKind, value: str) -> str:
        """Returns the call's token for this value, minting `[KIND#n]` (n per call and kind) on first sight."""
        kind = PiiKind(kind)
        digest = self._hmac(call_id, kind, value)
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                row = con.execute("SELECT token FROM pii_values WHERE call_id = ? AND value_hmac = ?",
                                  (call_id, digest)).fetchone()
                if row is not None:
                    return row["token"]
                count = con.execute("SELECT COUNT(*) FROM pii_values WHERE call_id = ? AND kind = ?",
                                    (call_id, kind)).fetchone()[0]
                token = token_for(kind, count + 1)
                ciphertext = self._fernet.encrypt(value.encode("utf-8")) if self._fernet else None
                con.execute(
                    "INSERT INTO pii_values (call_id, token, kind, value_hmac, ciphertext, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (call_id, token, kind, digest, ciphertext, self._now()))
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("COMMIT")
        return token

    def get_all(self, call_id: str) -> dict[str, dict]:
        """`{token: {"kind", "value"}}`; `value` is None for rows written without a key."""
        with self._connect() as con:
            rows = con.execute("SELECT token, kind, ciphertext FROM pii_values WHERE call_id = ? ORDER BY rowid",
                               (call_id,)).fetchall()
        out: dict[str, dict] = {}
        for r in rows:
            value = None
            if r["ciphertext"] is not None and self._fernet is not None:
                value = self._fernet.decrypt(bytes(r["ciphertext"])).decode("utf-8")
            out[r["token"]] = {"kind": r["kind"], "value": value}
        return out

    def delete_call(self, call_id: str) -> int:
        with self._connect() as con:
            cur = con.execute("DELETE FROM pii_values WHERE call_id = ?", (call_id,))
            return cur.rowcount
