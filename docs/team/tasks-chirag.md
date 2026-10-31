# Chirag: bank simulator tasks

You own the **bank simulator**: the mock loan origination, loan management, core banking, CSM ticketing, insurance and FAQ systems the voice agent reads from.

Read these before starting:
- `AGENTS.md`: the workflow and rules.
- The **Shared contract** section of `docs/superpowers/plans/2026-10-31-csm-voice-agent.md`. Its endpoints, JSON fields, enums and error codes are fixed. The voice agent is built against them in parallel, so don't rename anything. If something in the contract is impossible, stop and tell Anshuman.
- `docs/brief/problem-05.md`: what the judges check.

Status markers: `[ ]` todo · `[~]` in progress (add your name and the branch) · `[x]` merged into `develop`.

---

- [x] **C1: Move the simulator to `backend/simulator`, port 8090; restore the Spring API in Compose** (needs: none)

**Files:** move `backend/api/app/`, `backend/api/requirements.txt`, the Python `backend/api/Dockerfile` and `backend/api/tests/` (the Python tests) to `backend/simulator/`. Restore the Spring Dockerfile at `backend/api/Dockerfile` from `main` (`git show main:api/Dockerfile`). Update `docker-compose.yml`. Point `frontend/src/pages/BFSIAgentDesk.tsx` at nothing removed: see the last step.

- [ ] Step 1: `git mv` the Python app and its tests into `backend/simulator/` (`app/`, `tests/`, `requirements.txt`, `Dockerfile`). Restore the Spring `backend/api/Dockerfile` from `main`.
- [ ] Step 2: In the simulator Dockerfile, make the server listen on 8090 (`--port 8090`, `EXPOSE 8090`).
- [ ] Step 3: Compose:
  - `api` builds `./backend/api` (Spring, 8080);
  - add `simulator` building `./backend/simulator` with `ports: ["8090:8090"]` and a volume for its SQLite file (`./data/simulator:/app/data/runtime`);
  - `voice` gets `SIMULATOR_BASE=http://simulator:8090/v1`.
- [ ] Step 4: Delete the `chat`, `flows`, `analytics` and `caseintel` routers, and `cbs/cards`, along with their imports in `main.py`. Keep the `security/pii.py` and `security/audit.py` modules.
- [ ] Step 5: `/health` returns exactly `{"status": "ok", "service": "bank-simulator"}`, with no compliance claims.
- [ ] Step 6: `BFSIAgentDesk.tsx` calls `/api/v1/chat/message` and `/audit/entries`, which no longer exist. Remove the route from `frontend/src/App.tsx` and keep `components/PhoneSimulator.tsx`, which the operator panel reuses. Run `cd frontend && npx tsc --noEmit && npm test`.
- [ ] Step 7: Test (`backend/simulator/tests/test_health.py`): `GET /health` is 200 with the body above, and `GET /api/v1/chat/message` is 404. Run `cd backend/simulator && python -m pytest -q`.
- [ ] Step 8: Run `docker compose config` with no errors. Commit: `chore(simulator): move FastAPI bank simulator to backend/simulator on 8090; api builds Spring again`.

- [~] (Chirag, feat/c2-seed-and-store) **C2: Seed data and SQLite writes** (needs: C1)

**Files:** create `backend/simulator/data/seed/{customers,applications,loans,accounts,transactions,tickets,complaints,policies,claims}.json`, `backend/simulator/app/store.py` and `backend/simulator/app/enums.py`.

- [x] Step 1: `app/enums.py`: a `StrEnum` for each contract enum:
  - `Stage`, `ProductType`, `InstalmentStatus`, `Direction`, `TxnStatus`;
  - `TicketCategory`, `TicketStatus` (`OPEN`, `IN_PROGRESS`, `RESOLVED`, `CLOSED`);
  - `ComplaintCategory`, `Severity`;
  - `PolicyStatus` (`ACTIVE`, `LAPSED`, `EXPIRED`), `ClaimStatus` (`SUBMITTED`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`, `SETTLED`).
- [x] Step 2: Seed these 8 synthetic customers, each with a `customer_ref`, `first_name`, `last_name`, 10-digit `mobile` and `dob`. Dates are relative to today, computed at load time: store `"due_in_days": 5`, never fixed dates.

| ref | mobile / dob | Supports scenario |
|---|---|---|
| CUST-1001 Asha Verma | 9876500001 / 1990-04-12 | Personal loan application `LA-24001` in `DOCUMENT_VERIFICATION`, submitted 6 days ago, `next_step` "None required from you". No loan account yet, so the "first instalment" question has no schedule. |
| CUST-1002 Rahul Iyer | 9876500002 / 1985-11-03 | Personal loan `PL-31002` (EMI ₹12,450, due in 5 days) **and** vehicle loan `VL-31003` (EMI ₹9,800, due in 12 days), for the correction scenario. Savings account. Ticket `SR-40102` `STATEMENT` `IN_PROGRESS`. |
| CUST-1003 Fatima Khan | 9876500003 / 1992-07-21 | Vehicle loan `VL-31007` with an **overdue** instalment (₹9,800, 9 days) kept separate from the next one (₹9,800, due in 21 days). |
| CUST-1004 Arjun Nair | 9876500004 / 1978-02-14 | Savings account. `TXN-88213` transfer ₹15,000 `FAILED`, `recorded_reason` null. `TXN-88214` ₹2,300 `PENDING`. |
| CUST-1005 Meera Pillai | 9876500005 / 1988-09-30 | Health policy `HP-77001` `ACTIVE`, premium due in 18 days. Claim `CLM-7001` `UNDER_REVIEW`. Motor policy `MP-77002` `LAPSED`. |
| CUST-1006 Vikram Rao | 9876500006 / 1995-12-05 | Home loan `HL-90182`. Existing complaint `CMP-50011` `INCORRECT_CHARGE` `OPEN`. |
| CUST-1007 Sana Mirza | 9876500007 / 1999-05-18 | Application `LA-24009` `REJECTED`. Current account with a low balance. |
| CUST-1008 David Fernandes | 9876500008 / 1982-03-09 | `TXN-90011` card debit ₹48,999 `POSTED`, which the customer will say they didn't make (escalation scenario). |

- [x] Step 3: `app/store.py`. Load the JSON into memory at start-up; seeds are read-only. Writes (tickets, complaints, routed queries, escalations, verification attempts, sessions) go to SQLite at `data/runtime/simulator.db`, with the schema created on start. `reset()` empties the write tables. References are `SR-`, `CMP-`, `RQ-` and `ESC-` plus 5 digits, unique, starting at 40200, 50200, 60200 and 70200.
- [x] Step 4: Tests (`tests/test_store.py`):
  - the seeds load with 8 customers;
  - every loan's `next_instalment.due_date` is in the future;
  - `VL-31007.overdue.amount == 9800`;
  - a created ticket gets ref `SR-40200` and survives a store reload;
  - `reset()` removes it.
- [x] Step 5: Commit: `feat(simulator): seed data for the #05 scenarios and SQLite-backed writes`.

- [ ] **C3: Verification, sessions, lockout, ownership** (needs: C2)

**Files:** create `backend/simulator/app/routers/verify.py` and `backend/simulator/app/guard.py`.

- [ ] Step 1: Write the failing tests first (`tests/test_verify.py`):
  - the right mobile and dob give 200 with a `session`;
  - `+919876500002` and `09876500002` are normalised;
  - a wrong dob gives 401 `VERIFICATION_FAILED` with `attempts_left` of 2, then 1;
  - a third failure gives 423 `LOCKED`, and a later correct attempt is still 423 for 15 minutes (inject a clock);
  - `GET /v1/lms/loans` without the header gives 401 `NOT_VERIFIED`;
  - an expired session (more than 900 s) gives 401;
  - **CUST-1002's session fetching `/v1/lms/loans/VL-31007/schedule` (CUST-1003's) gives 403 `NOT_YOUR_RECORD`**;
  - a second verify on the same `call_id` replaces the first session.
- [ ] Step 2: Implement `POST /v1/verify` and the dependency `require_session(x_customer_session: str = Header(...)) -> Customer`, plus `owns(customer, record)`. Record every attempt with the `call_id` in the audit module.
- [ ] Step 3: Run the tests. Commit: `feat(simulator): customer verification with lockout and per-customer record guard`.

- [ ] **C4: LOS, LMS, CBS and insurance endpoints** (needs: C3)

**Files:** create `backend/simulator/app/routers/{los,lms,cbs,insurance}.py`.

- [ ] Step 1: Write the failing tests (`tests/test_records.py`), all with a verified session:
  - CUST-1001 `/v1/los/applications` has stage `DOCUMENT_VERIFICATION`;
  - CUST-1002 `/v1/lms/loans?type=vehicle` returns only `VL-31003`;
  - `/v1/lms/loans/PL-31002/schedule` has a `DUE` entry with amount 12450;
  - CUST-1004 `/v1/cbs/transactions?status=FAILED` returns `TXN-88213` with `recorded_reason` null;
  - CUST-1005 `/v1/insurance/claims` has `CLM-7001 UNDER_REVIEW`;
  - every list returns only the session customer's records;
  - an unknown `type` gives 422.
- [ ] Step 2: Implement exactly the contract's response fields. Amounts are integers in rupees. Dates are ISO `YYYY-MM-DD`.
- [ ] Step 3: Commit: `feat(simulator): loan, banking and insurance record endpoints`.

- [ ] **C5: CSM tickets, complaints, routed queries, escalations, ops** (needs: C3)

**Files:** create `backend/simulator/app/routers/csm.py` and `backend/simulator/app/routers/ops.py`.

- [ ] Step 1: Write the failing tests (`tests/test_csm.py`):
  - creating a ticket `REPAYMENT_SCHEDULE` for CUST-1002 gives 201 `SR-40200` `OPEN`, and `GET /v1/csm/tickets/SR-40200` returns it;
  - CUST-1003 reading `SR-40102` gives 403;
  - a complaint `UNAUTHORISED_TRANSACTION` gives `escalated: true`;
  - `SERVICE_EXPERIENCE`/`LOW` gives `escalated: false`;
  - `POST /v1/csm/routed` works **without** a session;
  - an unknown category gives 422;
  - `GET /v1/ops/records?kind=routed` without Basic auth gives 401, and with `ops:ops` lists the record;
  - `POST /v1/ops/reset` empties the writes.
- [ ] Step 2: Implement it. Every write stores the `call_id` and a `created_at` timestamp.
- [ ] Step 3: Commit: `feat(simulator): CSM tickets, complaints, routed queries, escalations and ops listing`.

- [ ] **C6: FAQ search; final clean-up** (needs: C2; content from P1)

**Files:** create `backend/simulator/app/routers/faq.py`. Data lives in `backend/simulator/data/seed/faq.json`. Until Pavan's P1 is merged, use 3 placeholder entries with the same schema: `{id, question, answer, tags, source}`.

- [ ] Step 1: Write the failing tests (`tests/test_faq.py`):
  - "what documents do I need for a vehicle loan" puts the vehicle-loan documents entry first;
  - "how do I stop auto debit" matches the NACH entry;
  - "what's the weather today" returns `items: []`. This is the **unsupported** signal, so use a minimum score threshold.
- [ ] Step 2: Implement `GET /v1/faq/search` with SQLite FTS5 (bm25) over the question, answer and tags, built at start-up. Return `score` as a positive float, and drop results below the threshold.
- [ ] Step 3: `grep -rniE "compliant|RBI|DPDP|PCI|zero hallucination|production-grade" backend/simulator` returns nothing. No hard-coded statistics remain anywhere in the simulator.
- [ ] Step 4: Commit: `feat(simulator): FAQ search with an approved-answer threshold`.
