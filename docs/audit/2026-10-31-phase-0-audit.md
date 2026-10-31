# Phase 0: System Architecture & Scenario Audit Report

**Date**: 2026-10-31  
**Project**: Azentio-CSM Voice Agent (#05)  
**Author**: Senior AI Engineer / Architect  

---

## 1. Context: Current State

- **Stack**:
  - **STT**: Silero VAD (voice activity detection), Groq Whisper (`whisper-large-v3-turbo`) via `backend/voice/app/speech.py` and `backend/voice/app/speech_file.py`.
  - **TTS**: Microsoft Neural TTS (`edge-tts`, default `en-IN-NeerjaNeural`) via `backend/voice/app/edge_tts_service.py`.
  - **LLM**: Model-agnostic fallback chain (`backend/voice/app/llm_chain.py`) supporting Groq LLaMA 3.3 70B, Google Gemini 2.0 Flash, and Mistral Large/Small. Anthropic models are strictly prohibited. Parallel intent classification via `backend/voice/app/intents.py`.
  - **Voice Pipeline**: Pipecat 1.12 (`backend/voice/app/support_pipeline.py` & `main.py` WebRTC/Twilio/Audio simulation) on port `7861`.
  - **Bank Simulator**: FastAPI (`backend/simulator`) on port `8090`, backed by `backend/simulator/app/store.py` with in-memory seed data and SQLite (`data/runtime/simulator.db`).
  - **System of Record (SoR)**: Spring Boot (`backend/api`) on port `8080` with Flyway migrations (`V1` to `V4__support_calls.sql`) tracking call outcomes and turns.
  - **Frontend**: React 18 + TypeScript + Vite on port `5173` with `SupportDesk.tsx`, `SupportCall.tsx` (live WebRTC & transcript inspector), and `PhoneSimulator.tsx`.

- **Working Today**:
  - Voice turn loop (WebRTC + Audio simulation `/sim/audio`).
  - SQLite data store & in-memory seed data covering 8 synthetic customers and scenarios.
  - Parallel intent classification (`backend/voice/app/intents.py`).
  - Support tools dispatch logic with client-side verification guards (`support_tools.py`).
  - Spring Boot call session & turn metadata recording (`/api/v1/support/calls`).
  - React Support Desk and Support Call live operator views.

- **Known Issues & Gaps**:
  - **Simulator HTTP Endpoints Not Mounted**: While `store.py` has all logic, `backend/simulator/app/main.py` does not yet mount `/v1/verify`, `/v1/los/*`, `/v1/lms/*`, `/v1/cbs/*`, `/v1/csm/*`, or `/v1/insurance/*`. Live calls calling simulator receive 404!
  - **Lockout Enforcement**: Lockout is currently tracked only in the voice agent's in-memory `CallSession`; callers can bypass lockout by hanging up and calling again. Must be enforced at simulator level using SQLite `verification_attempts`.
  - **PII in Voice Prompt History**: Raw customer speech is appended to conversation history without PII redaction.
  - **Multilingual**: System prompt explicitly says "English only". No Hindi or Arabic prompt, TTS voice, or STT configuration.

---

## 2. Actual Architecture & Data Flow

```
[Customer Audio] 
       │
       ▼
[Silero VAD + Groq Whisper] ──(Transcript)──► [SupportBrain.reply()]
                                                    │
                      ┌─────────────────────────────┴─────────────────────────────┐
                      ▼                                                           ▼
         [Parallel Intent Classifier]                                    [LLM with Support Tools]
             (LOAN, REPAYMENT, etc.)                                              │
                      │                                                           ▼
                      │                                                [support_tools.py]
                      │                                                (Client Guard: Verified?)
                      │                                                           │
                      │                                                           ▼
                      │                                                [SimulatorClient HTTP]
                      │                                                           │
                      │                                                           ▼
                      │                                               [FastAPI Simulator :8090]
                      │                                                           │
                      │                                                           ▼
                      │                                                  [BankStore (SQLite)]
                      │                                                           │
                      └─────────────────────────────┬─────────────────────────────┘
                                                    │
                                                    ▼
                                         [Spring Boot API :8080]
                                      (V4 Support Calls & Metadata)
                                                    │
                                                    ▼
                                          [React UI Desk :5173]
```

---

## 3. Scenario Coverage Matrix (10 Required Scenarios)

| # | Scenario | Status | Key Code References | Audit Details & Deficiencies |
|---|---|---|---|---|
| **1** | **Loan Status** | **Partial** | `backend/voice/app/support_tools.py`: `get_loan_applications`<br>`backend/simulator/app/store.py`: `get_applications` | Tool and store logic exist (`CUST-1001` Asha Verma, `LA-24001` in `DOCUMENT_VERIFICATION`). **Gap**: FastAPI endpoint `GET /v1/los/applications` is not yet mounted in simulator router (Task C4). Voice tool receives 404 from simulator if called live! |
| **2** | **EMI Enquiry** | **Partial** | `backend/voice/app/support_tools.py`: `get_loans`, `get_schedule`<br>`backend/simulator/app/store.py`: `get_loans`, `get_loan_schedule` | Store has `PL-31002` (₹12,450) & `VL-31003` (₹9,800), and `VL-31007` (overdue ₹9,800). **Gap**: Router `GET /v1/lms/loans` and `/schedule` not yet mounted in `backend/simulator/app/main.py` (Task C4). |
| **3** | **Account / Transaction Enquiry** | **Partial** | `backend/voice/app/support_tools.py`: `get_accounts`, `get_transactions`<br>`backend/simulator/app/store.py`: `get_accounts`, `get_transactions` | Seeds exist (`TXN-88213` failed, `TXN-88214` pending, `TXN-90011` posted). **Gap**: Router `GET /v1/cbs/accounts` & `GET /v1/cbs/transactions` not yet mounted to `/v1` in simulator (Task C4). |
| **4** | **Service Request Create + Track** | **Partial** | `backend/voice/app/support_tools.py`: `create_service_request`, `get_ticket`<br>`backend/simulator/app/store.py`: `create_ticket`, `get_ticket` | SQLite sequence `SR-40200` implemented and tested in store. **Gap**: `POST /v1/csm/tickets` and `GET /v1/csm/tickets/{ref}` router missing from `backend/simulator/app/main.py` (Task C5). |
| **5** | **Complaint + Escalation** | **Partial** | `backend/voice/app/support_tools.py`: `register_complaint`, `escalate_to_human`<br>`backend/simulator/app/store.py`: `create_complaint`, `create_escalation` | Auto-escalation on fraud/unauthorized (`CMP-50200`, `ESC-70200`) implemented in store. **Gap**: `POST /v1/csm/complaints` & `POST /v1/csm/escalations` routers not yet mounted (Task C5). |
| **6** | **Insurance Policy / Claim** | **Partial** | `backend/voice/app/support_tools.py`: `get_policies`, `get_claims`<br>`backend/simulator/app/store.py`: `get_policies`, `get_claims` | Seeds for `CUST-1005` (Health `HP-77001` active, Motor `MP-77002` lapsed, Claim `CLM-7001` under review) exist. **Gap**: `GET /v1/insurance/*` routers not mounted (Task C4). |
| **7** | **Multi-Intent** | **Implemented** | `backend/voice/app/intents.py`: `classify`<br>`backend/voice/app/support_brain.py`: `_loop`<br>`backend/voice/app/support_prompt.py` | `intents.py` returns list of intents; prompt directs agent to handle sequential requests without restarting; `MAX_TOOL_ROUNDS = 6` allows chained tool execution in single turn. |
| **8** | **Interruption / Correction** | **Implemented** | `backend/voice/app/support_brain.py`: `reply`<br>`backend/voice/app/support_tools.py`<br>`backend/voice/app/support_prompt.py` | Prompt explicitly handles: "if the caller corrects you (e.g. 'no, my vehicle loan'), call the tool again with corrected details without re-verifying". Session stays active in `CallSession`. |
| **9** | **Auth Failure + Sensitive Requests** | **Partial** | `backend/voice/app/support_tools.py`: `verify_customer`, `run_support_tool`<br>`backend/simulator/app/store.py`: `record_verification_attempt`, `is_locked` | Guard in `support_tools.py` intercepts `PERSONAL` tools when `not call.verified` or `call.locked`. **Gap**: Simulator endpoint `POST /v1/verify` router not mounted (Task C3). Lockout check is not enforced at simulator HTTP layer yet. |
| **10** | **Multilingual** | **Missing** | `backend/voice/app/support_prompt.py`<br>`backend/voice/app/config.py` | Prompt currently enforces `"English only"`. No Hindi/Arabic prompts, no STT language auto-detection, no Indic/Arabic TTS voices, and no RTL support in dashboard. |

---

## 4. Risks & Vulnerabilities Identified

1. **Simulator HTTP Endpoints Unconnected (P0 - Showstopper)**:
   - Voice agent tools call `http://localhost:8090/v1/verify`, `/v1/los/applications`, `/v1/lms/loans`, etc. The simulator currently returns `404 Not Found` because routers are not yet mounted in `backend/simulator/app/main.py`.
2. **Lockout Bypass Vulnerability (P0 - Security)**:
   - In-memory `CallSession.verify_failures` resets when caller hangs up and calls again. Lockout check must be enforced server-side against SQLite `verification_attempts` table.
3. **Cross-Customer Data Exposure Risk (P0 - Security)**:
   - Need simulator-side `require_session` dependency and `owns(customer, record)` guard to ensure caller A cannot query caller B's loan schedule with `403 NOT_YOUR_RECORD`.
4. **PII Leakage in LLM Context (P1 - Compliance)**:
   - Unredacted customer utterances enter the prompt history. Aadhaar/PAN/Card numbers spoken by customer must be sanitized before LLM ingress.
5. **Hallucination on Missing Data (P0 - Correctness)**:
   - If a tool fails or is empty, LLM must not guess interest rates, balances, or statuses.

---

## 5. Prioritized Fix List

### P0 (Would Fail a Live Evaluation)
1. **Simulator Routers Implementation**:
   - `verify.py`: `POST /v1/verify` (returns 200, 401 with attempts_left, 423 LOCKED).
   - `guard.py`: `require_session` dependency & record ownership check.
   - `los.py`: `GET /v1/los/applications`.
   - `lms.py`: `GET /v1/lms/loans` and `/schedule`.
   - `cbs.py`: `GET /v1/cbs/accounts` and `/transactions`.
   - `csm.py`: `POST /v1/csm/tickets`, `POST /v1/csm/complaints`, `POST /v1/csm/routed`, `POST /v1/csm/escalations`, `GET /v1/csm/tickets/{ref}`.
   - `insurance.py`: `GET /v1/insurance/policies` and `/claims`.
2. **Server-Side Lockout & Session Guard**:
   - Enforce 15-minute lockout across distinct calls for the same mobile.
3. **Grounding & Spoken Numbers**:
   - Enforce rupee amounts spoken as exact words (`spoken_inr`), never rounded or estimated.

### P1 (Quality & Stability)
1. **PII Masking at Ingress**:
   - Redact Aadhaar, PAN, and Card numbers before logging and prompt assembly.
2. **FAQ Search with SQLite FTS5**:
   - Implement `/v1/faq/search` with BM25 score threshold; return empty items on off-topic questions.
3. **Voice Loop VAD & Barge-in Tuning**:
   - Clean audio pipeline cancellation on interruption.

### P2 (Polish & Multilingual)
1. **Multilingual Support (Hindi, Arabic)**:
   - Prompts, number formatting, dynamic TTS voice selection (`hi-IN-SwaraNeural`, `ar-XA-AminaNeural`).
2. **Dashboard Real-time Telemetry**:
   - Verify live transcript sync, intent badges, and escalation alerts in `SupportDesk.tsx`.
