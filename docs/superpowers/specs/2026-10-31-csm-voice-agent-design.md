# CSM Voice Agent: Level 1 design

Problem #05 of the Azentio.ai Build Labs challenge pack, Level 1 ("Understand customer voice requests and provide accurate assistance"). Finale: 31 Oct 2026. Branch: `develop`.

## Intent

A customer calls a bank's service line and speaks naturally. The agent:
- works out what the customer wants, including several requests in one call;
- checks who the customer is before revealing anything personal;
- answers from simulated bank systems, never inventing values;
- opens tickets and complaints with reference numbers;
- refuses and routes anything it cannot or may not handle.

An operator screen shows each step as it happens.

Judges award points for observable behaviour. They run hidden tests, including unseen utterances with accents and background noise, and check three things: the intent, the ticket, and the refusal on unsupported requests.

## Goals (each line is something a judge can see)

| # | Brief requirement | What the judge sees |
|---|---|---|
| G1 | Voice input, transcript on screen | Live mic call in the browser. The recognised text appears on the operator panel within a second of the end of speech. |
| G2 | Reproducible audio-file simulation | Upload one or more WAV/MP3 files, or run `scripts/simulate_audio.py <dir>`. Same audio processing as the live call; same panel output; a JSON/markdown report. |
| G3 | Natural phrasings → one intent | "When is my next EMI?", "How much do I pay next month?" and "Tell me my next loan instalment" all show **Repayment**. |
| G4 | Six intents, plus clarify | Loan application, Repayment, Account, Service request (status), Product question (FAQ), Complaint. Unclear → the agent asks a clarifying question and the panel shows **Unclear**. |
| G5 | Multiple intents, kept context, corrections | "Status of my loan, and when is my first instalment?" handles both. "No, my vehicle loan" switches the loan without restarting the call. |
| G6 | Verification before personal data | FAQ answers need no verification. Balances, loans, transactions and tickets need it. Failed attempts are counted and shown. Another customer's data is refused **by the simulator**, not only by the prompt. |
| G7 | Values only from data | Every amount, date and status the agent says appears in that turn's "Retrieved" panel. |
| G8 | Service request creation and tracking | "Send me my repayment schedule" creates a ticket. The agent reads back the reference (e.g. `SR-48213`); asking about that reference later returns its status. |
| G9 | Complaints, sensitive matters, unsupported requests | A complaint gets a category, a severity and a reference. Unauthorised transactions, fraud and anger escalate to a human. An unsupported question gets a polite refusal plus a routed-query record with a reason. |
| G10 | Spoken replies, text alongside | Short conversational speech, never raw JSON. The text is shown with each reply. |
| G11 | Operator panel | Recognised speech, intent(s), verification status, retrieved information, agent reply, history. Start and End buttons. A list of calls, tickets, complaints and escalations. |
| G12 | Accent and noise robustness | A test set of Indian, British, Nigerian and American voices, clean and with background chatter, run through G2. The report shows intent accuracy, ticket correctness and refusal rate. |

## Non-goals (Level 1)
- Real telephony as the main channel. Twilio stays optional.
- Languages other than English. Hindi is a stretch goal, attempted only after G1–G12.
- Outbound calling.
- New renewal features. Renewal Desk is reused as-is.

## Anti-goals (a failure even if the demo "works")
- Any spoken figure not present in retrieved data.
- Any personal detail revealed before verification, or one customer's data reaching another.
- Hard-coded dashboard statistics or canned latency numbers.
- Compliance claims in UI or docs.

## Architecture

```
Browser (frontend :5173)
  ├─ live call (WebRTC) ──────► voice :7861 ─┬─► bank simulator :8090 (FastAPI)  LOS · LMS · CBS · CSM tickets · insurance · FAQ
  ├─ audio-file simulation ───► voice :7861  ├─► Spring API :8080   calls · turns · audit · dashboard · Renewal Desk
  └─ operator panel ──────────► Spring :8080 └─► Groq (STT + LLM, fallback Gemini/Mistral), Edge TTS
```

### Bank simulator: `backend/api/app` on port 8090 (owner: Chirag)
- **Seed data:** JSON files under `backend/api/data/`, loaded at start-up:
  - about 8 customers with verification attributes (date of birth and last 4 digits of phone);
  - loan applications with stages (submitted, document verification, credit review, sanctioned, rejected);
  - loan accounts with schedules, distinguishing the next instalment from overdue amounts;
  - bank accounts and transactions, including pending and failed ones;
  - service requests;
  - insurance policies and claims;
  - FAQ / product entries, each with an id.
- **Writes** (new tickets, complaints, routed queries) go to SQLite.
- **Verification:** `POST /v1/verify {customer_ref, dob, phone_last4}` returns a short-lived session token bound to one customer. Every personal endpoint requires it and returns only that customer's records. It rejects other customers with 403, and the agent says so.
- **Endpoints:**
  - `GET /v1/los/applications`
  - `GET /v1/lms/loans[?type=]` and `/v1/lms/loans/{id}/schedule`
  - `GET /v1/cbs/accounts`, `/v1/cbs/transactions[?status=&ref=]`
  - `GET /v1/csm/tickets/{ref}`, `POST /v1/csm/tickets`, `POST /v1/csm/complaints`, `POST /v1/csm/routed`
  - `GET /v1/insurance/policies`, `/v1/insurance/claims`
  - `GET /v1/faq/search?q=` (unauthenticated; returns entry ids for citation)
  - `GET /v1/ops/tickets` (lists for the operator panel)
- **Remove** the hard-coded analytics and renewal numbers. Compose gets a `simulator` service on 8090; `api` builds the Spring app again.

### Voice agent: `backend/voice` (owner: Anshuman)
- **Front-desk tools:**
  - `verify_customer`
  - `get_loan_applications`, `get_loans`, `get_schedule`
  - `get_accounts`, `get_transactions`
  - `get_ticket`, `create_service_request`, `register_complaint`
  - `get_policies`, `get_claims`
  - `search_faq`
  - `route_unsupported(reason)`, `escalate_to_human(reason)`
  - `end_call`
  - `handoff_renewal` (switches to the Renewal Desk prompt and tools in the same call)
- **Tool layer guards:** every personal tool refuses without a session token, so a refusal doesn't rely on the prompt.
- **Intent:** classified per customer turn by a small fast model (JSON: one or more intents from the enum, plus `unclear`). It runs **in parallel** with the reply, so it adds no latency, and is posted to the call record. The prompt still instructs the agent to ask a clarifying question when the request is unclear.
- **Speech front end** (exact values come from `spikes/stt-bench/report.md`):
  - Silero voice detection tuned with a confidence and volume floor, about 200 ms lead-in and trimmed silence;
  - Smart Turn end-of-turn detection, if it keeps paused sentences whole;
  - 16 kHz mono FLAC upload;
  - Whisper domain prompt and language pinned to English;
  - the best model from the benchmark (Groq Whisper large-v3 / turbo or Sarvam);
  - a filter that drops invented transcripts (high no-speech probability or known phantom phrases);
  - noise reduction only if the benchmark shows it helps.
- **Audio-file simulation:** `POST /sim/audio` (multipart, one file per customer turn) runs the **same** speech front end, then the brain with tools. It returns per turn: the transcript, intents, verification status, tool trace with retrieved data, the reply text, and the reply audio. `scripts/simulate_audio.py` runs a folder of scenarios and writes `report.md`.

### Spring API: `backend/api/src` on port 8080 (owner: Anshuman)
- Migration `V4`:
  - make `calls.policy_id` nullable;
  - add `calls.kind` (`SUPPORT` | `RENEWAL`);
  - add a `turn_meta` JSON column per turn (intents, verification, retrieved data, tool trace, ticket refs);
  - add `calls.outcome`.
- Endpoints to start a support call, record turns with metadata, end the call, and list calls with outcome filters. The dashboard counts come from these rows. Existing audit chain entries cover each call event.

### Operator panel: `frontend` (owner: Anshuman, with Chirag's desk components reused where they fit)
- **Live call view:**
  - transcript stream (customer and agent);
  - an intent chip per customer turn;
  - verification badge;
  - "Retrieved" card per turn (the simulator data used);
  - reply text;
  - Start and End buttons;
  - an "Upload audio" tab for G2.
- **Lists:** calls (with outcome), tickets, complaints, routed queries and escalations. Clicking a call opens its full turn history.

### Evaluation: owner Pavan (scripts and scenario content), Anshuman (harness)
- `eval/scenarios/*.yaml`: the brief's 10 scenarios as scripted customer turns, with expected intents, ticket fields, refusals and "must not say" values.
- The utterances are rendered as audio in 4 accents, clean and noisy (reusing the benchmark generator), and run through `/sim/audio`.
- The report has intent accuracy, ticket correctness, refusal correctness, disclosure-before-verification violations (target 0) and latency p50/p95.

## Decisions from the builder review
- **Brief:** the #05 scenarios and Level 1 capabilities are summarised in `docs/brief/problem-05.md`. Eval scripts and seed data follow it.
- **How a caller identifies:** by saying their registered 10-digit mobile number, then their date of birth. A browser call has no caller ID, and a spoken mobile number survives accents better than an alphanumeric customer ID.
  - "Another customer's data" means a verified caller quoting a loan, ticket or policy reference that belongs to someone else. The simulator returns 403 `NOT_YOUR_RECORD`.
  - Saying a different mobile number mid-call starts a new verification, which replaces the session; the change is logged.
- **Judges' input:** we support all three routes with one output shape: live mic, file upload on the panel, and `POST /sim/audio`. Intent names are our own enum, shown in plain words on the panel. The `/sim/audio` JSON is documented in the README.
- **Quota:**
  - The intent classifier uses the smallest Groq model with JSON output (`openai/gpt-oss-20b`), with keyword rules as an offline fallback.
  - The eval runs a sample of 1 accent, clean, by default. `--full` runs all accents and noise.
  - The voice service accepts `GROQ_API_KEYS` (comma-separated) and rotates on 429.
- **Existing FastAPI app:**
  - becomes the simulator at `backend/simulator` on 8090;
  - keeps its `pii` and `audit` modules;
  - drops `chat`, `flows`, `analytics`, `cbs/cards` and the compliance claims in `/health`.
  - The agent-desk page's phone simulator component is reused in the operator panel. The page itself is replaced by the panel route, so nothing calls the removed chat routes.
- **Renewal Desk handoff:** a stretch goal (A11) after Level 1. It needs simulator insurance policies mapped to Spring renewal policies, plus a carried-over verification.

## Open items
- Organiser sample data or schemas, if they arrive, replace the seed files.
- Hindi (scenario 10) is a stretch goal.

## Builder's calls (decided here, revisit if wrong)
- Intent classification runs in parallel instead of as a mandatory tool call, to protect latency.
- Tickets live in the simulator (it is the "CSM platform" in the brief). Spring stores refs and summaries per turn for the panel.
- One process handles both front desk and Renewal Desk; the handoff is a prompt and tool swap, not a second call.
