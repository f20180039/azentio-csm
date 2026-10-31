"""SQLite-backed storage for System-of-Record API (Support calls, Renewals, Cases, Audit)."""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApiStore:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or settings.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._seed_data()

    def _get_connection(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _init_db(self) -> None:
        with self._get_connection() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS support_calls (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    outcome TEXT
                );

                CREATE TABLE IF NOT EXISTS support_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    at TEXT NOT NULL,
                    meta TEXT NOT NULL,
                    FOREIGN KEY(call_id) REFERENCES support_calls(id)
                );

                CREATE TABLE IF NOT EXISTS renewal_policies (
                    policy_no TEXT PRIMARY KEY,
                    customer_name TEXT NOT NULL,
                    mobile TEXT NOT NULL,
                    dob TEXT NOT NULL,
                    product TEXT NOT NULL,
                    premium INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    expiry_date TEXT NOT NULL,
                    lapse_risk REAL NOT NULL,
                    addons TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS renewal_calls (
                    call_id TEXT PRIMARY KEY,
                    policy_no TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    greeting TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    verified INTEGER NOT NULL DEFAULT 0,
                    outcome TEXT
                );

                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY,
                    case_type TEXT NOT NULL,
                    customer_ref TEXT NOT NULL,
                    status TEXT NOT NULL,
                    score REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    details TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entity_ref TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    curr_hash TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )
            con.commit()

    def _seed_data(self) -> None:
        with self._get_connection() as con:
            count = con.execute("SELECT COUNT(*) FROM renewal_policies").fetchone()[0]
            if count == 0:
                policies = [
                    (
                        "POL-90124",
                        "Asha Verma",
                        "9876500001",
                        "1990-04-12",
                        "Comprehensive Motor",
                        12800,
                        "ACTIVE",
                        "2026-11-20",
                        0.78,
                        json.dumps(["Zero Depreciation", "Roadside Assistance"]),
                    ),
                    (
                        "POL-90125",
                        "Rahul Iyer",
                        "9876500002",
                        "1985-11-03",
                        "Family Health Protect",
                        18500,
                        "ACTIVE",
                        "2026-11-15",
                        0.42,
                        json.dumps(["Critical Illness Rider", "OPD Cover"]),
                    ),
                    (
                        "POL-90126",
                        "Meera Pillai",
                        "9876500005",
                        "1988-09-30",
                        "Health Shield Optima",
                        14200,
                        "ACTIVE",
                        "2026-11-28",
                        0.65,
                        json.dumps(["Hospital Cash", "Maternity Cover"]),
                    ),
                ]
                con.executemany(
                    """
                    INSERT INTO renewal_policies (policy_no, customer_name, mobile, dob, product, premium, status, expiry_date, lapse_risk, addons)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    policies,
                )

            case_count = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            if case_count == 0:
                demo_cases = [
                    (
                        "CASE-101",
                        "demo",
                        "CUST-1001",
                        "OPEN",
                        0.35,
                        _now_iso(),
                        json.dumps({"findings": [], "summary": "Income verification check"}),
                    ),
                    (
                        "CASE-102",
                        "demo",
                        "CUST-1004",
                        "REVIEW",
                        0.82,
                        _now_iso(),
                        json.dumps({"findings": [], "summary": "High risk duplicate transfer flagged"}),
                    ),
                ]
                con.executemany(
                    """
                    INSERT INTO cases (id, case_type, customer_ref, status, score, created_at, details)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    demo_cases,
                )
            con.commit()

    # -------------------------------------------------------------------------
    # Support Calls
    # -------------------------------------------------------------------------
    def start_support_call(self, channel: str, call_id: str | None = None) -> str:
        cid = call_id or str(uuid.uuid4())
        now = _now_iso()
        with self._get_connection() as con:
            con.execute(
                "INSERT INTO support_calls (id, channel, started_at) VALUES (?, ?, ?)",
                (cid, channel, now),
            )
            con.commit()
        return cid

    def add_support_turn(self, call_id: str, role: str, text: str, at: str, meta: dict) -> int:
        with self._get_connection() as con:
            seq_row = con.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM support_turns WHERE call_id = ?",
                (call_id,),
            ).fetchone()
            seq = int(seq_row[0]) if seq_row else 1
            con.execute(
                """
                INSERT INTO support_turns (call_id, seq, role, text, at, meta)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (call_id, seq, role, text, at, json.dumps(meta or {})),
            )
            con.commit()
            return seq

    def patch_support_meta(self, call_id: str, seq: int, meta: dict) -> bool:
        with self._get_connection() as con:
            row = con.execute(
                "SELECT meta FROM support_turns WHERE call_id = ? AND seq = ?",
                (call_id, seq),
            ).fetchone()
            if not row:
                return False
            current = json.loads(row["meta"])
            current.update(meta)
            con.execute(
                "UPDATE support_turns SET meta = ? WHERE call_id = ? AND seq = ?",
                (json.dumps(current), call_id, seq),
            )
            con.commit()
            return True

    def end_support_call(self, call_id: str, outcome: str) -> bool:
        now = _now_iso()
        with self._get_connection() as con:
            con.execute(
                "UPDATE support_calls SET ended_at = ?, outcome = ? WHERE id = ?",
                (now, outcome, call_id),
            )
            con.commit()
            return True

    def get_support_call(self, call_id: str) -> dict[str, Any] | None:
        with self._get_connection() as con:
            call = con.execute(
                "SELECT * FROM support_calls WHERE id = ?", (call_id,)
            ).fetchone()
            if not call:
                return None
            turns_rows = con.execute(
                "SELECT seq, role, text, at, meta FROM support_turns WHERE call_id = ? ORDER BY seq ASC",
                (call_id,),
            ).fetchall()
            turns = []
            verified = False
            for r in turns_rows:
                m = json.loads(r["meta"])
                if m.get("verified"):
                    verified = True
                turns.append({
                    "seq": r["seq"],
                    "role": r["role"],
                    "text": r["text"],
                    "at": r["at"],
                    "meta": m,
                })
            return {
                "id": call["id"],
                "channel": call["channel"],
                "startedAt": call["started_at"],
                "endedAt": call["ended_at"],
                "outcome": call["outcome"],
                "verified": verified,
                "turns": turns,
            }

    def list_support_calls(
        self, outcome: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._get_connection() as con:
            query = "SELECT * FROM support_calls"
            params: list[Any] = []
            if outcome:
                query += " WHERE outcome = ?"
                params.append(outcome)
            query += " ORDER BY started_at DESC LIMIT ?"
            params.append(limit)

            rows = con.execute(query, params).fetchall()
            items = []
            for r in rows:
                cid = r["id"]
                turn_stats = con.execute(
                    "SELECT COUNT(*), meta FROM support_turns WHERE call_id = ?",
                    (cid,),
                ).fetchall()
                turn_count = len(turn_stats)
                intents_set = set()
                verified = False
                for t in turn_stats:
                    try:
                        m = json.loads(t[1])
                        for i in m.get("intents", []):
                            intents_set.add(i)
                        if m.get("verified"):
                            verified = True
                    except Exception:
                        pass
                items.append({
                    "id": cid,
                    "channel": r["channel"],
                    "startedAt": r["started_at"],
                    "endedAt": r["ended_at"],
                    "outcome": r["outcome"],
                    "verified": verified,
                    "turnCount": turn_count,
                    "intents": sorted(intents_set),
                })
            return items

    # -------------------------------------------------------------------------
    # Renewals
    # -------------------------------------------------------------------------
    def get_renewals_queue(self) -> list[dict[str, Any]]:
        with self._get_connection() as con:
            rows = con.execute("SELECT * FROM renewal_policies").fetchall()
            return [
                {
                    "policyNumber": r["policy_no"],
                    "customerName": r["customer_name"],
                    "mobile": r["mobile"],
                    "product": r["product"],
                    "premium": r["premium"],
                    "status": r["status"],
                    "expiryDate": r["expiry_date"],
                    "lapseRisk": r["lapse_risk"],
                    "addons": json.loads(r["addons"]),
                }
                for r in rows
            ]

    def get_renewals_dashboard(self) -> dict[str, Any]:
        return {
            "totalPolicies": 3,
            "highRiskCount": 1,
            "renewedCount": 0,
            "retentionRate": 0.85,
            "targetRetention": 0.90,
        }

    def start_renewal_call(self, policy_no: str) -> dict[str, Any]:
        with self._get_connection() as con:
            p = con.execute(
                "SELECT * FROM renewal_policies WHERE policy_no = ?", (policy_no,)
            ).fetchone()
            call_id = str(uuid.uuid4())
            name = p["customer_name"] if p else "Valued Customer"
            greeting = f"Hello {name}, this is Azentio Insurance following up on policy renewal."
            con.execute(
                """
                INSERT INTO renewal_calls (call_id, policy_no, customer_name, greeting, started_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (call_id, policy_no, name, greeting, _now_iso()),
            )
            con.commit()
            return {"callId": call_id, "greeting": greeting}

    def get_renewal_call(self, call_id: str) -> dict[str, Any] | None:
        with self._get_connection() as con:
            row = con.execute(
                "SELECT * FROM renewal_calls WHERE call_id = ?", (call_id,)
            ).fetchone()
            if not row:
                return None
            return {
                "callId": row["call_id"],
                "policyNo": row["policy_no"],
                "customerName": row["customer_name"],
                "greeting": row["greeting"],
                "startedAt": row["started_at"],
                "endedAt": row["ended_at"],
                "verified": bool(row["verified"]),
                "outcome": row["outcome"],
            }

    # -------------------------------------------------------------------------
    # Audit Ledger
    # -------------------------------------------------------------------------
    def record_audit(self, actor: str, action: str, entity_ref: str, payload: dict) -> None:
        now = _now_iso()
        payload_str = json.dumps(payload)
        with self._get_connection() as con:
            last = con.execute(
                "SELECT curr_hash FROM audit_ledger ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev_hash = last[0] if last else "GENESIS_HASH"
            curr_hash = hashlib.sha256(
                f"{actor}{action}{entity_ref}{payload_str}{prev_hash}{now}".encode()
            ).hexdigest()
            con.execute(
                """
                INSERT INTO audit_ledger (actor, action, entity_ref, payload, prev_hash, curr_hash, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (actor, action, entity_ref, payload_str, prev_hash, curr_hash, now),
            )
            con.commit()

    def verify_audit(self) -> dict[str, Any]:
        with self._get_connection() as con:
            rows = con.execute("SELECT * FROM audit_ledger ORDER BY id ASC").fetchall()
            prev = "GENESIS_HASH"
            for r in rows:
                expected = hashlib.sha256(
                    f"{r['actor']}{r['action']}{r['entity_ref']}{r['payload']}{prev}{r['timestamp']}".encode()
                ).hexdigest()
                if r["curr_hash"] != expected:
                    return {"valid": False, "corruptedId": r["id"]}
                prev = r["curr_hash"]
            return {"valid": True, "entriesCount": len(rows)}


store = ApiStore()
