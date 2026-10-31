# CSM Voice Agent Level 1: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Teammates' agents: do not work from this file directly. Start at `AGENTS.md`, which routes you to your own task file.**

**Goal:** An inbound banking customer-service voice agent that meets problem #05 Level 1.
- It hears natural, accented and noisy speech.
- It classifies intents and verifies the caller before revealing personal data.
- It answers from simulated bank systems.
- It opens tickets and complaints with references.
- It routes unsupported requests.
- It shows every step on an operator panel.

**Architecture:** The FastAPI bank simulator (port 8090) serves loan applications, loan accounts, core banking, CSM tickets, insurance and FAQ data from seed files. Its writes go to SQLite. The Pipecat voice service (port 7861) calls the simulator through guarded tools and records every turn's metadata in the Spring API (port 8080). The React operator panel reads Spring for calls and the simulator for tickets. A recorded-audio path runs the same speech front end, so the judges' files behave exactly like live speech.

**Tech Stack:**
- Python 3.12: FastAPI, Pipecat 1.12.0, Silero VAD, Groq Whisper.
- Java 21: Spring Boot, Flyway, Postgres.
- React + TypeScript (Vite).
- edge-tts, ffmpeg.

**Spec:** `docs/superpowers/specs/2026-10-31-csm-voice-agent-design.md`

## Global Constraints
- **Never use Anthropic models or `ANTHROPIC_API_KEY`.** LLMs are Groq first, then Gemini and Mistral. Keys live only in `.env`, which is never committed and never printed.
- **Synthetic data only.** No real names, phone numbers, Aadhaar or PAN numbers.
- **No hard-coded statistics** anywhere. Every number on a screen or in speech comes from stored data.
- **No compliance claims** ("RBI compliant", "zero hallucinations", "production-grade") in UI, docs or prompts.
- **Fixed vocabularies are `StrEnum`s:** intents, ticket and complaint categories, statuses, stages. Input is parsed and validated at the API boundary; unknown values get a 422.
- **Every amount, date and status the agent speaks** must be in that turn's tool results.
- **Personal endpoints require a verified customer session, enforced by the simulator.** Prompt instructions alone don't count.
- **Every task ships with tests, and the service's suite stays green.**
- **Git:**
  - One branch per task: `feat/<task-id>-<slug>`, cut from `develop`.
  - Open a PR into `develop`; don't push to `main`.
  - Before you start, run `git pull` on `develop`.

## Review Focus
1. **A verified customer asks for another customer's record.** The simulator returns 403 `NOT_YOUR_RECORD` and the agent declines. Test: C3.
2. **Noise-only or silent audio.** It produces no customer turn and no reply. Tests: A6, A7.
3. **Mid-call correction ("no, my vehicle loan").** The next repayment answer uses the vehicle loan, without re-verifying. Test: A2.
4. **Unsupported question after a service request.** The ticket remains, and a routed-query record exists with the question and reason. Tests: A2, P2 scenario `08-unsupported-after-request`.
5. **Three failed verifications.** The customer is locked for 15 minutes and every personal tool keeps refusing. Tests: C3, A1.

---

## Shared contract: bank simulator HTTP API (base `http://localhost:8090/v1`)

All bodies are JSON. Errors look like `{"error": CODE, "detail": str}`. Personal endpoints need the header `X-Customer-Session: <token>`. Without it, or with an expired token, they return 401 `NOT_VERIFIED`. A record owned by someone else returns 403 `NOT_YOUR_RECORD`.

**Verification**
- `POST /verify` with `{"mobile": "9876504821", "dob": "1990-04-12", "call_id": "<uuid>"}` (10 digits; a leading +91 or 0 is stripped)
  - success: 200 `{"session", "expires_in": 900, "customer": {"customer_ref", "first_name"}}`
  - wrong details: 401 `{"error": "VERIFICATION_FAILED", "attempts_left": n}`
  - after 3 failures within 15 minutes: 423 `{"error": "LOCKED"}`
  - A new verify within the same `call_id` replaces the previous session and is logged.

**Loan applications (LOS)**
- `GET /los/applications` returns `{"items": [{"ref", "product", "amount", "stage", "stage_label", "submitted_on", "next_step"}]}`
- `stage` is one of `SUBMITTED`, `DOCUMENT_VERIFICATION`, `CREDIT_REVIEW`, `SANCTIONED`, `DISBURSED`, `REJECTED`.

**Loan accounts (LMS)**
- `GET /lms/loans?type=personal|vehicle|home` returns `{"items": [{"loan_id", "product", "product_type", "outstanding_principal", "next_instalment": {"amount", "due_date"}, "overdue": {"amount", "since"} | null, "status"}]}`
- `GET /lms/loans/{loan_id}/schedule` returns `{"loan_id", "items": [{"n", "due_date", "amount", "status": "PAID|DUE|OVERDUE|UPCOMING"}]}`

**Core banking (CBS)**
- `GET /cbs/accounts` returns `{"items": [{"account_id", "type", "masked_number", "balance", "currency"}]}`
- `GET /cbs/transactions?status=&ref=&limit=10` returns `{"items": [{"ref", "date", "description", "amount", "direction": "DEBIT|CREDIT", "status": "POSTED|PENDING|FAILED", "recorded_reason": str|null}]}`

**CSM platform**

| Request | Body | Returns |
|---|---|---|
| `GET /csm/tickets` | | the caller's own tickets |
| `GET /csm/tickets/{ref}` | | `{"ref", "category", "status", "summary", "created_on", "updated_on"}` |
| `POST /csm/tickets` | `{"category", "summary", "details": {}, "call_id"}` | 201 `{"ref": "SR-#####", "status": "OPEN", "eta_days"}` |
| `POST /csm/complaints` | `{"category", "description", "severity": "LOW\|MEDIUM\|HIGH", "call_id"}` | 201 `{"ref": "CMP-#####", "status": "OPEN", "escalated": bool}` |
| `POST /csm/routed` (no session) | `{"query_text", "reason", "call_id", "customer_ref": str\|null}` | 201 `{"ref": "RQ-#####"}` |
| `POST /csm/escalations` (session optional) | `{"reason", "summary", "call_id"}` | 201 `{"ref": "ESC-#####"}` |

- Ticket `category` is one of `STATEMENT`, `REPAYMENT_SCHEDULE`, `ACCOUNT_DOCUMENT`, `ADDRESS_CHANGE`, `OTHER`.
- Complaint `category` is one of `FAILED_TRANSACTION`, `INCORRECT_CHARGE`, `UNAUTHORISED_TRANSACTION`, `SERVICE_EXPERIENCE`, `OTHER`.
- `escalated` is true when the category is `UNAUTHORISED_TRANSACTION` or the severity is `HIGH`.

**Insurance**
- `GET /insurance/policies` returns `{"items": [{"policy_no", "product", "status", "premium", "premium_due_date", "sum_insured", "coverage_status"}]}`
- `GET /insurance/claims` returns `{"items": [{"claim_no", "policy_no", "status", "submitted_on", "amount_claimed", "amount_approved": int|null}]}`

**FAQ** (no session)
- `GET /faq/search?q=&limit=3` returns `{"items": [{"id": "FAQ-012", "question", "answer", "score"}]}`, with the best match first. An empty `items` means no approved answer.

**Operations** (HTTP Basic `ops:ops`)
- `GET /ops/records?kind=ticket|complaint|routed|escalation` lists every record, newest first.
- `POST /ops/reset` reloads the seed data and empties the writes.

**Health**
- `GET /health` returns `{"status": "ok"}`.

The seed customers and the scenario each one supports are listed in C2. The voice agent's tests mock this contract with `httpx.MockTransport`, so nobody waits on anyone.

---

## Task index

| ID | Owner | Task | Needs |
|---|---|---|---|
| C1 | Chirag | Move simulator to `backend/simulator`; Compose: `simulator` on 8090, `api` builds Spring again | none |
| C2 | Chirag | Seed data (8 customers, scenario coverage) and SQLite writes | C1 |
| C3 | Chirag | Verification, sessions, lockout, ownership guard | C2 |
| C4 | Chirag | LOS, LMS, CBS and insurance endpoints | C3 |
| C5 | Chirag | CSM tickets, complaints, routed, escalations, ops list and reset | C3 |
| C6 | Chirag | FAQ search (SQLite FTS5) over P1 content; remove hard-coded stats routes | C2, P1 |
| P1 | Pavan | FAQ and product knowledge: 30 entries | none |
| P2 | Pavan | 10 brief scenarios plus unsupported/unclear, as YAML scripts | none |
| P3 | Pavan | Intent utterance set: 60 labelled lines | none |
| P4 | Pavan | Audio renderer: 4 accents, clean and noisy, from P2/P3 | P2, P3 |
| A1 | Anshuman | Simulator client and support tools with the session guard | contract |
| A2 | Anshuman | Support prompt, corrections, Renewal Desk handoff, routing | A1 |
| A3 | Anshuman | Parallel intent classifier | none |
| A4 | Anshuman | Spring V4: support calls, `turn_meta`, outcome, list | none |
| A5 | Anshuman | Voice records turn metadata; support call start in voice | A1, A3, A4 |
| A6 | Anshuman | Speech front end tuned from the benchmark | STT report |
| A7 | Anshuman | Audio-file simulation endpoint and CLI | A5, A6 |
| A8 | Anshuman | Operator panel: live call view and lists | A4, A5 |
| A9 | Anshuman | Eval harness over P2/P4 through `/sim/audio`, plus report | A7, P4 |
| A10 | Anshuman | README, demo checklist, final run on fresh data | all |
| A11 | Anshuman | Stretch: Renewal Desk handoff with carried-over verification | A2, Level 1 done |

The full task text is in `docs/team/tasks-chirag.md`, `docs/team/tasks-pavan.md` and `docs/team/tasks-anshuman.md`.
