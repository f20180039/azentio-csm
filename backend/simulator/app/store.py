"""In-memory seed data loader and SQLite-backed dynamic store for the Bank Simulator."""
import json
import os
import re
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.enums import (
    ClaimStatus,
    ComplaintCategory,
    Direction,
    InstalmentStatus,
    LockScope,
    PolicyStatus,
    ProductType,
    RecordKind,
    RefPrefix,
    Severity,
    VerifyOutcome,
    Stage,
    TICKET_DEPARTMENT,
    TicketCategory,
    TicketStatus,
    TxnStatus,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_SEED_DIR = DEFAULT_DATA_DIR / "seed"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "runtime" / "simulator.db"

INITIAL_COUNTERS = {
    RefPrefix.TICKET: 40199,
    RefPrefix.COMPLAINT: 50199,
    RefPrefix.ROUTED: 60199,
    RefPrefix.ESCALATION: 70199,
}

# Columns added after C2; existing runtime databases get them via ALTER TABLE.
ADDED_COLUMNS = {
    "verification_attempts": {"customer_ref": "TEXT", "caller_key": "TEXT", "target_key": "TEXT", "outcome": "TEXT"},
    "escalations": {"category": "TEXT"},
    "tickets": {"progress": "TEXT", "department": "TEXT"},
}


def _now_iso(dt: datetime | None = None) -> str:
    current = dt or datetime.now(timezone.utc)
    return current.isoformat()


class BankStore:
    def __init__(
        self,
        db_path: Path | str | None = None,
        seed_dir: Path | str | None = None,
        today: date | None = None,
    ):
        self.db_path = Path(db_path or os.getenv("SIMULATOR_DB_PATH") or DEFAULT_DB_PATH)
        self.seed_dir = Path(seed_dir or os.getenv("SIMULATOR_SEED_DIR") or DEFAULT_SEED_DIR)
        self._fixed_today = today
        self.today = today or date.today()

        # In-memory seed containers
        self.customers: dict[str, dict[str, Any]] = {}
        self.applications: list[dict[str, Any]] = []
        self.loans: list[dict[str, Any]] = []
        self.accounts: list[dict[str, Any]] = []
        self.transactions: list[dict[str, Any]] = []
        self.seed_tickets: list[dict[str, Any]] = []
        self.seed_complaints: list[dict[str, Any]] = []
        self.policies: list[dict[str, Any]] = []
        self.claims: list[dict[str, Any]] = []

        # Ensure directories exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.seed_dir.mkdir(parents=True, exist_ok=True)

        self._init_db()
        self.load_seeds(self.today)

    def _get_connection(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _init_db(self) -> None:
        with self._get_connection() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS reference_counters (
                    prefix TEXT PRIMARY KEY,
                    last_val INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    ref TEXT PRIMARY KEY,
                    customer_ref TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details TEXT,
                    call_id TEXT,
                    eta_days INTEGER NOT NULL DEFAULT 2,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS complaints (
                    ref TEXT PRIMARY KEY,
                    customer_ref TEXT,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    description TEXT NOT NULL,
                    escalated INTEGER NOT NULL DEFAULT 0,
                    call_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routed_queries (
                    ref TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    customer_ref TEXT,
                    call_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS escalations (
                    ref TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    customer_ref TEXT,
                    call_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS verification_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mobile TEXT NOT NULL,
                    dob TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    attempted_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    customer_ref TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS lockouts (
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    locked_until TEXT NOT NULL,
                    PRIMARY KEY (scope, key)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS faq_fts USING fts5(
                    id,
                    question,
                    answer,
                    tags,
                    tokenize = 'porter'
                );
                """
            )
            for table, columns in ADDED_COLUMNS.items():
                existing = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
                for column, sql_type in columns.items():
                    if column not in existing:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
            for prefix, val in INITIAL_COUNTERS.items():
                con.execute(
                    "INSERT OR IGNORE INTO reference_counters (prefix, last_val) VALUES (?, ?)",
                    (prefix, val),
                )
            con.commit()

    def _next_ref(self, prefix: str) -> str:
        with self._get_connection() as con:
            row = con.execute(
                """
                UPDATE reference_counters
                SET last_val = last_val + 1
                WHERE prefix = ?
                RETURNING last_val
                """,
                (prefix,),
            ).fetchone()
            if not row:
                raise RuntimeError(f"Unknown reference counter prefix: {prefix}")
            con.commit()
            return f"{prefix}-{row[0]}"

    def load_seeds(self, today: date | None = None) -> None:
        ref_date = today or self.today or date.today()
        self.today = ref_date

        def read_seed(name: str) -> Any:
            path = self.seed_dir / f"{name}.json"
            if not path.exists():
                return []
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

        # 1. Customers
        raw_custs = read_seed("customers")
        self.customers = {c["customer_ref"]: c for c in raw_custs}

        # 2. Applications (relative: submitted_days_ago)
        raw_apps = read_seed("applications")
        self.applications = []
        for app in raw_apps:
            item = dict(app)
            days = item.pop("submitted_days_ago", 0)
            item["submitted_on"] = (ref_date - timedelta(days=days)).isoformat()
            self.applications.append(item)

        # 3. Loans (relative: due_in_days, since_days_ago)
        raw_loans = read_seed("loans")
        self.loans = []
        for l in raw_loans:
            item = json.loads(json.dumps(l))  # deep copy
            if "next_instalment" in item and item["next_instalment"]:
                d_in_days = item["next_instalment"].pop("due_in_days", 0)
                item["next_instalment"]["due_date"] = (ref_date + timedelta(days=d_in_days)).isoformat()
            if item.get("overdue"):
                s_days = item["overdue"].pop("since_days_ago", 0)
                item["overdue"]["since"] = (ref_date - timedelta(days=s_days)).isoformat()
            if "schedule" in item:
                for inst in item["schedule"]:
                    inst_d = inst.pop("due_in_days", 0)
                    inst["due_date"] = (ref_date + timedelta(days=inst_d)).isoformat()
            self.loans.append(item)

        # 4. Accounts
        self.accounts = read_seed("accounts")

        # 5. Transactions (relative: days_ago)
        raw_txns = read_seed("transactions")
        self.transactions = []
        for txn in raw_txns:
            item = dict(txn)
            d_ago = item.pop("days_ago", 0)
            item["date"] = (ref_date - timedelta(days=d_ago)).isoformat()
            self.transactions.append(item)

        # 6. Seed Tickets (relative: days_ago)
        raw_tickets = read_seed("tickets")
        self.seed_tickets = []
        for t in raw_tickets:
            item = dict(t)
            d_ago = item.pop("days_ago", 0)
            d_str = (ref_date - timedelta(days=d_ago)).isoformat()
            item["created_on"] = d_str
            item["updated_on"] = d_str
            item["department"] = str(TICKET_DEPARTMENT[TicketCategory(item["category"])])
            self.seed_tickets.append(item)

        # 7. Seed Complaints (relative: days_ago)
        raw_complaints = read_seed("complaints")
        self.seed_complaints = []
        for c in raw_complaints:
            item = dict(c)
            d_ago = item.pop("days_ago", 0)
            item["created_at"] = (ref_date - timedelta(days=d_ago)).isoformat()
            self.seed_complaints.append(item)

        # 8. Policies (relative: due_in_days)
        raw_policies = read_seed("policies")
        self.policies = []
        for p in raw_policies:
            item = dict(p)
            d_in_days = item.pop("due_in_days", 0)
            item["premium_due_date"] = (ref_date + timedelta(days=d_in_days)).isoformat()
            self.policies.append(item)

        # 9. Claims (relative: submitted_days_ago)
        raw_claims = read_seed("claims")
        self.claims = []
        for cl in raw_claims:
            item = dict(cl)
            d_ago = item.pop("submitted_days_ago", 0)
            item["submitted_on"] = (ref_date - timedelta(days=d_ago)).isoformat()
            self.claims.append(item)

        # 10. FAQs (FTS5 index with Porter stemmer)
        self.seed_faqs = read_seed("faq")
        with self._get_connection() as con:
            con.execute("DELETE FROM faq_fts")
            for item in self.seed_faqs:
                tags_str = " ".join(item.get("tags", []))
                con.execute(
                    "INSERT INTO faq_fts (id, question, answer, tags) VALUES (?, ?, ?, ?)",
                    (item["id"], item["question"], item["answer"], tags_str),
                )
            con.commit()

    def reset(self) -> None:
        """Empties all write tables (lockouts included), resets reference counters and reloads the seed."""
        with self._get_connection() as con:
            for table in ("tickets", "complaints", "routed_queries", "escalations",
                          "verification_attempts", "sessions", "lockouts"):
                con.execute(f"DELETE FROM {table}")
            for prefix, val in INITIAL_COUNTERS.items():
                con.execute(
                    "UPDATE reference_counters SET last_val = ? WHERE prefix = ?",
                    (val, prefix),
                )
            con.commit()
        self.load_seeds(self._fixed_today or date.today())

    # -------------------------------------------------------------------------
    # Verification & Sessions
    # -------------------------------------------------------------------------
    def record_verification_attempt(
        self,
        mobile: str,
        dob: str,
        call_id: str,
        success: bool,
        attempted_at: datetime | None = None,
        *,
        outcome: VerifyOutcome | None = None,
        customer_ref: str | None = None,
        caller_key: str | None = None,
        target_key: str | None = None,
    ) -> None:
        resolved = outcome or (VerifyOutcome.SUCCESS if success else VerifyOutcome.FAILED)
        with self._get_connection() as con:
            con.execute(
                """
                INSERT INTO verification_attempts
                    (mobile, dob, call_id, success, attempted_at, outcome, customer_ref, caller_key, target_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (mobile, dob, call_id, 1 if success else 0, _now_iso(attempted_at), str(resolved),
                 customer_ref, caller_key, target_key or mobile),
            )
            con.commit()

    def count_target_failures(self, target_key: str, since: datetime) -> int:
        """Failed attempts against one customer (or unknown mobile) since `since`, not counting any before its last success."""
        with self._get_connection() as con:
            last_ok_id = con.execute(
                "SELECT MAX(id) FROM verification_attempts WHERE target_key = ? AND outcome = ?",
                (target_key, str(VerifyOutcome.SUCCESS)),
            ).fetchone()[0]
            row = con.execute(
                """
                SELECT COUNT(*) FROM verification_attempts
                WHERE target_key = ? AND outcome = ? AND attempted_at >= ? AND id > ?
                """,
                (target_key, str(VerifyOutcome.FAILED), since.isoformat(), last_ok_id or 0),
            ).fetchone()
            return int(row[0])

    def caller_failure_stats(self, caller_key: str, since: datetime) -> tuple[int, int]:
        """(failed attempts, distinct customers or mobiles failed) for one caller since `since`."""
        with self._get_connection() as con:
            row = con.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT target_key) FROM verification_attempts
                WHERE caller_key = ? AND outcome = ? AND attempted_at >= ?
                """,
                (caller_key, str(VerifyOutcome.FAILED), since.isoformat()),
            ).fetchone()
            return int(row[0]), int(row[1])

    def set_lock(self, scope: LockScope, key: str, until: datetime) -> None:
        with self._get_connection() as con:
            con.execute(
                "INSERT OR REPLACE INTO lockouts (scope, key, locked_until) VALUES (?, ?, ?)",
                (str(scope), key, until.isoformat()),
            )
            con.commit()

    def is_locked(self, scope: LockScope, key: str, now: datetime) -> bool:
        with self._get_connection() as con:
            row = con.execute(
                "SELECT locked_until FROM lockouts WHERE scope = ? AND key = ?",
                (str(scope), key),
            ).fetchone()
            return bool(row) and row["locked_until"] > now.isoformat()

    def create_session(
        self,
        customer_ref: str,
        call_id: str,
        ttl_seconds: int = 900,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        cur_dt = now or datetime.now(timezone.utc)
        expires_dt = cur_dt + timedelta(seconds=ttl_seconds)
        token = uuid.uuid4().hex

        with self._get_connection() as con:
            # A new verify within the same call_id replaces previous session
            con.execute("DELETE FROM sessions WHERE call_id = ?", (call_id,))
            con.execute(
                """
                INSERT INTO sessions (token, customer_ref, call_id, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token, customer_ref, call_id, cur_dt.isoformat(), expires_dt.isoformat()),
            )
            con.commit()

        return {
            "session": token,
            "expires_in": ttl_seconds,
            "customer_ref": customer_ref,
            "call_id": call_id,
        }

    def get_session(self, token: str, now: datetime | None = None) -> dict[str, Any] | None:
        cur_dt = now or datetime.now(timezone.utc)
        cur_str = cur_dt.isoformat()
        with self._get_connection() as con:
            row = con.execute(
                "SELECT token, customer_ref, call_id, created_at, expires_at FROM sessions WHERE token = ?",
                (token,),
            ).fetchone()
            if not row:
                return None
            if row["expires_at"] < cur_str:
                return None
            return dict(row)

    # -------------------------------------------------------------------------
    # Customers
    # -------------------------------------------------------------------------
    def get_customer(self, customer_ref: str) -> dict[str, Any] | None:
        return self.customers.get(customer_ref)

    def find_customer(self, mobile: str, dob: str) -> dict[str, Any] | None:
        # mobile should be normalized 10 digits
        clean_mobile = "".join(c for c in mobile if c.isdigit())[-10:]
        for c in self.customers.values():
            if c["mobile"] == clean_mobile and c["dob"] == dob:
                return c
        return None

    # -------------------------------------------------------------------------
    # LOS (Loan Origination System)
    # -------------------------------------------------------------------------
    def get_applications(self, customer_ref: str) -> list[dict[str, Any]]:
        return [
            {
                "ref": a["ref"],
                "product": a["product"],
                "amount": a["amount"],
                "stage": a["stage"],
                "stage_label": a["stage_label"],
                "submitted_on": a["submitted_on"],
                "next_step": a["next_step"],
            }
            for a in self.applications
            if a["customer_ref"] == customer_ref
        ]

    # -------------------------------------------------------------------------
    # LMS (Loan Management System)
    # -------------------------------------------------------------------------
    def get_loans(self, customer_ref: str, product_type: str | None = None) -> list[dict[str, Any]]:
        results = []
        for l in self.loans:
            if l["customer_ref"] != customer_ref:
                continue
            if product_type and l["product_type"].lower() != product_type.lower():
                continue
            results.append({
                "loan_id": l["loan_id"],
                "product": l["product"],
                "product_type": l["product_type"],
                "outstanding_principal": l["outstanding_principal"],
                "next_instalment": {
                    "amount": l["next_instalment"]["amount"],
                    "due_date": l["next_instalment"]["due_date"],
                },
                "overdue": (
                    {
                        "amount": l["overdue"]["amount"],
                        "since": l["overdue"]["since"],
                    }
                    if l.get("overdue")
                    else None
                ),
                "status": l["status"],
            })
        return results

    def get_loan(self, loan_id: str) -> dict[str, Any] | None:
        for l in self.loans:
            if l["loan_id"].upper() == loan_id.upper():
                return l
        return None

    def get_loan_schedule(self, loan_id: str) -> dict[str, Any] | None:
        loan = self.get_loan(loan_id)
        if not loan:
            return None
        return {
            "loan_id": loan["loan_id"],
            "items": [
                {
                    "n": item["n"],
                    "due_date": item["due_date"],
                    "amount": item["amount"],
                    "status": item["status"],
                }
                for item in loan.get("schedule", [])
            ],
        }

    # -------------------------------------------------------------------------
    # CBS (Core Banking System)
    # -------------------------------------------------------------------------
    def get_accounts(self, customer_ref: str) -> list[dict[str, Any]]:
        return [
            {
                "account_id": a["account_id"],
                "type": a["type"],
                "masked_number": a["masked_number"],
                "balance": a["balance"],
                "currency": a["currency"],
            }
            for a in self.accounts
            if a["customer_ref"] == customer_ref
        ]

    def get_transactions(
        self,
        customer_ref: str,
        status: str | None = None,
        ref: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        results = []
        for txn in self.transactions:
            if txn["customer_ref"] != customer_ref:
                continue
            if status and txn["status"].upper() != status.upper():
                continue
            if ref and txn["ref"].upper() != ref.upper():
                continue
            results.append({
                "ref": txn["ref"],
                "date": txn["date"],
                "description": txn["description"],
                "amount": txn["amount"],
                "direction": txn["direction"],
                "status": txn["status"],
                "recorded_reason": txn.get("recorded_reason"),
            })
            if len(results) >= limit:
                break
        return results

    # -------------------------------------------------------------------------
    # CSM (Tickets, Complaints, Routed Queries, Escalations)
    # -------------------------------------------------------------------------
    def create_ticket(
        self,
        customer_ref: str,
        category: str,
        summary: str,
        details: dict[str, Any] | None,
        call_id: str,
        eta_days: int = 2,
    ) -> dict[str, Any]:
        ref = self._next_ref(RefPrefix.TICKET)
        now_str = _now_iso()
        details_json = json.dumps(details or {})
        department = str(TICKET_DEPARTMENT[TicketCategory(category)])
        progress = f"Received by the {department} team."
        with self._get_connection() as con:
            con.execute(
                """
                INSERT INTO tickets (ref, customer_ref, category, status, summary, details, call_id, eta_days,
                                     department, progress, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ref, customer_ref, str(category), str(TicketStatus.OPEN), summary, details_json, call_id, eta_days,
                 department, progress, now_str, now_str),
            )
            con.commit()
        return {
            "ref": ref,
            "status": TicketStatus.OPEN,
            "eta_days": eta_days,
        }

    @staticmethod
    def _ticket_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "ref": row["ref"],
            "customer_ref": row["customer_ref"],
            "category": row["category"],
            "status": row["status"],
            "summary": row["summary"],
            "details": json.loads(row["details"]) if row["details"] else {},
            "call_id": row["call_id"],
            "eta_days": row["eta_days"],
            "department": row["department"],
            "progress": row["progress"],
            "created_on": row["created_at"][:10],
            "updated_on": row["updated_at"][:10],
        }

    @staticmethod
    def _ticket_from_seed(t: dict[str, Any]) -> dict[str, Any]:
        return {
            "ref": t["ref"],
            "customer_ref": t["customer_ref"],
            "category": t["category"],
            "status": t["status"],
            "summary": t["summary"],
            "details": {},
            "call_id": None,
            "eta_days": t.get("eta_days"),
            "department": t["department"],
            "progress": t.get("progress"),
            "created_on": t["created_on"][:10],
            "updated_on": t["updated_on"][:10],
        }

    def _seed_ticket(self, ref_upper: str) -> dict[str, Any] | None:
        return next((t for t in self.seed_tickets if t["ref"].upper() == ref_upper), None)

    def get_ticket(self, ref: str) -> dict[str, Any] | None:
        ref_upper = ref.strip().upper()
        # Check SQLite writes first
        with self._get_connection() as con:
            row = con.execute("SELECT * FROM tickets WHERE ref = ?", (ref_upper,)).fetchone()
            if row:
                return self._ticket_from_row(row)
        seed = self._seed_ticket(ref_upper)
        return self._ticket_from_seed(seed) if seed else None

    def get_tickets(self, customer_ref: str) -> list[dict[str, Any]]:
        # Dynamic SQLite tickets first, then the seed
        with self._get_connection() as con:
            rows = con.execute(
                "SELECT * FROM tickets WHERE customer_ref = ? ORDER BY created_at DESC",
                (customer_ref,),
            ).fetchall()
        results = [self._ticket_from_row(row) for row in rows]
        results += [self._ticket_from_seed(t) for t in self.seed_tickets if t["customer_ref"] == customer_ref]
        return results

    def update_ticket(self, ref: str, status: TicketStatus, progress: str | None = None) -> dict[str, Any] | None:
        """Moves a ticket (SQLite or seed) to `status`, replacing its progress note when one is given; None if unknown.

        Seed tickets change in memory only, so reset() restores them."""
        ref_upper = ref.strip().upper()
        with self._get_connection() as con:
            cur = con.execute(
                "UPDATE tickets SET status = ?, progress = COALESCE(?, progress), updated_at = ? WHERE ref = ?",
                (str(status), progress, _now_iso(), ref_upper),
            )
            con.commit()
            if cur.rowcount:
                return self.get_ticket(ref_upper)
        seed = self._seed_ticket(ref_upper)
        if seed is None:
            return None
        seed["status"] = str(status)
        if progress is not None:
            seed["progress"] = progress
        seed["updated_on"] = self.today.isoformat()  # seed dates are relative to the simulator's start
        return self._ticket_from_seed(seed)

    def create_complaint(
        self,
        customer_ref: str | None,
        category: str,
        description: str,
        severity: str,
        call_id: str,
    ) -> dict[str, Any]:
        ref = self._next_ref(RefPrefix.COMPLAINT)
        now_str = _now_iso()
        cat_str = str(category)
        sev_str = str(severity).upper()
        escalated = (
            cat_str == ComplaintCategory.UNAUTHORISED_TRANSACTION.value
            or sev_str == Severity.HIGH.value
        )
        with self._get_connection() as con:
            con.execute(
                """
                INSERT INTO complaints (ref, customer_ref, category, severity, status, description, escalated, call_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ref, customer_ref, cat_str, sev_str, str(TicketStatus.OPEN), description, 1 if escalated else 0, call_id, now_str),
            )
            con.commit()
        return {
            "ref": ref,
            "status": TicketStatus.OPEN,
            "escalated": escalated,
        }

    def get_complaint(self, ref: str) -> dict[str, Any] | None:
        ref_upper = ref.strip().upper()
        with self._get_connection() as con:
            row = con.execute("SELECT * FROM complaints WHERE ref = ?", (ref_upper,)).fetchone()
            if row:
                return {
                    "ref": row["ref"],
                    "customer_ref": row["customer_ref"],
                    "category": row["category"],
                    "severity": row["severity"],
                    "status": row["status"],
                    "description": row["description"],
                    "escalated": bool(row["escalated"]),
                    "call_id": row["call_id"],
                    "created_at": row["created_at"],
                }
        for c in self.seed_complaints:
            if c["ref"].upper() == ref_upper:
                return dict(c)
        return None

    def get_complaints(self, customer_ref: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with self._get_connection() as con:
            rows = con.execute(
                "SELECT * FROM complaints WHERE customer_ref = ? ORDER BY created_at DESC",
                (customer_ref,),
            ).fetchall()
            for row in rows:
                results.append({
                    "ref": row["ref"],
                    "category": row["category"],
                    "severity": row["severity"],
                    "status": row["status"],
                    "description": row["description"],
                    "escalated": bool(row["escalated"]),
                    "created_at": row["created_at"],
                })
        for c in self.seed_complaints:
            if c["customer_ref"] == customer_ref:
                results.append({
                    "ref": c["ref"],
                    "category": c["category"],
                    "severity": c["severity"],
                    "status": c["status"],
                    "description": c["description"],
                    "escalated": c["escalated"],
                    "created_at": c["created_at"],
                })
        return results

    def create_routed(
        self,
        query_text: str,
        reason: str,
        call_id: str,
        customer_ref: str | None = None,
    ) -> dict[str, Any]:
        ref = self._next_ref(RefPrefix.ROUTED)
        now_str = _now_iso()
        with self._get_connection() as con:
            con.execute(
                """
                INSERT INTO routed_queries (ref, query_text, reason, customer_ref, call_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ref, query_text, reason, customer_ref, call_id, now_str),
            )
            con.commit()
        return {"ref": ref}

    def create_escalation(
        self,
        reason: str,
        summary: str,
        call_id: str,
        customer_ref: str | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        ref = self._next_ref(RefPrefix.ESCALATION)
        now_str = _now_iso()
        with self._get_connection() as con:
            con.execute(
                """
                INSERT INTO escalations (ref, reason, summary, customer_ref, call_id, created_at, category)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ref, reason, summary, customer_ref, call_id, now_str, str(category) if category else None),
            )
            con.commit()
        return {"ref": ref}

    # -------------------------------------------------------------------------
    # Insurance
    # -------------------------------------------------------------------------
    def get_policies(self, customer_ref: str) -> list[dict[str, Any]]:
        return [
            {
                "policy_no": p["policy_no"],
                "product": p["product"],
                "status": p["status"],
                "premium": p["premium"],
                "premium_due_date": p["premium_due_date"],
                "sum_insured": p["sum_insured"],
                "coverage_status": p["coverage_status"],
            }
            for p in self.policies
            if p["customer_ref"] == customer_ref
        ]

    def get_claims(self, customer_ref: str) -> list[dict[str, Any]]:
        return [
            {
                "claim_no": c["claim_no"],
                "policy_no": c["policy_no"],
                "status": c["status"],
                "submitted_on": c["submitted_on"],
                "amount_claimed": c["amount_claimed"],
                "amount_approved": c.get("amount_approved"),
            }
            for c in self.claims
            if c["customer_ref"] == customer_ref
        ]

    # -------------------------------------------------------------------------
    # Ops list
    # -------------------------------------------------------------------------
    def list_records(self, kind: RecordKind | None = None) -> list[dict[str, Any]]:
        """Every ticket, complaint, routed query and escalation (or one kind), newest first, in the ops item shape."""
        kinds = [RecordKind(kind)] if kind else list(RecordKind)
        results: list[dict[str, Any]] = []

        def item(ref, k, category, status, summary, customer_ref, call_id, created_at, escalated,
                 department=None, progress=None):
            return {"ref": ref, "kind": str(k), "category": category, "status": status, "summary": summary,
                    "customer_ref": customer_ref, "call_id": call_id, "created_at": created_at, "escalated": escalated,
                    "department": department, "progress": progress}

        with self._get_connection() as con:
            if RecordKind.TICKET in kinds:
                for r in con.execute("SELECT * FROM tickets"):
                    results.append(item(r["ref"], RecordKind.TICKET, r["category"], r["status"], r["summary"],
                                        r["customer_ref"], r["call_id"], r["created_at"], None,
                                        r["department"], r["progress"]))
                for t in self.seed_tickets:
                    results.append(item(t["ref"], RecordKind.TICKET, t["category"], t["status"], t["summary"],
                                        t["customer_ref"], None, t["created_on"], None,
                                        t["department"], t.get("progress")))
            if RecordKind.COMPLAINT in kinds:
                for r in con.execute("SELECT * FROM complaints"):
                    results.append(item(r["ref"], RecordKind.COMPLAINT, r["category"], r["status"], r["description"],
                                        r["customer_ref"], r["call_id"], r["created_at"], bool(r["escalated"])))
                for c in self.seed_complaints:
                    results.append(item(c["ref"], RecordKind.COMPLAINT, c["category"], c["status"], c["description"],
                                        c["customer_ref"], None, c["created_at"], c["escalated"]))
            if RecordKind.ROUTED in kinds:
                for r in con.execute("SELECT * FROM routed_queries"):
                    results.append(item(r["ref"], RecordKind.ROUTED, None, None, f"{r['query_text']} - {r['reason']}",
                                        r["customer_ref"], r["call_id"], r["created_at"], None))
            if RecordKind.ESCALATION in kinds:
                for r in con.execute("SELECT * FROM escalations"):
                    results.append(item(r["ref"], RecordKind.ESCALATION, r["category"], None,
                                        f"{r['summary']} ({r['reason']})", r["customer_ref"], r["call_id"],
                                        r["created_at"], True))
        results.sort(key=lambda r: (r["created_at"] or "", r["ref"]), reverse=True)
        return results

    # -------------------------------------------------------------------------
    # FAQ Search (FTS5 BM25 with Porter stemming)
    # -------------------------------------------------------------------------
    def search_faq(
        self,
        query: str,
        limit: int = 3,
        threshold: float = 2.0,
    ) -> list[dict[str, Any]]:
        if not query or not query.strip():
            return []
        stop_words = {
            "what", "whats", "who", "when", "where", "how", "is", "are", "do",
            "does", "did", "i", "you", "a", "an", "the", "for", "to", "of",
            "in", "my", "me", "can", "tell", "please", "get", "know", "want", "need"
        }
        words = re.findall(r"\w+", query.lower())
        content_words = [w for w in words if w not in stop_words]
        if not content_words:
            return []
        match_query = " OR ".join(f'"{w}"' for w in content_words)
        with self._get_connection() as con:
            cur = con.execute(
                """
                SELECT id, question, answer, round(-bm25(faq_fts, 0.0, 10.0, 1.0, 5.0), 2) as score
                FROM faq_fts
                WHERE faq_fts MATCH ?
                ORDER BY score DESC
                LIMIT ?
                """,
                (match_query, limit),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "question": r["question"],
                    "answer": r["answer"],
                    "score": float(r["score"]),
                }
                for r in rows
                if r["score"] >= threshold
            ]


# Global singleton instance
store = BankStore()
