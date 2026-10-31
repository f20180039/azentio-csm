# Anshuman: voice agent, call records, operator panel, evaluation

You own:
- the voice agent (`backend/voice`);
- the Spring call records (`backend/api/src`);
- the operator panel (`frontend`);
- the evaluation harness.

Work against the **Shared contract** in `docs/superpowers/plans/2026-10-31-csm-voice-agent.md`. Tests mock the simulator with `httpx.MockTransport`. Intent labels are the same as in `docs/team/tasks-pavan.md`.

Status markers: `[ ]` todo · `[~]` in progress · `[x]` merged into `develop`.

---

- [x] **A1: Simulator client and support tools** (needs: none)

**Files:** create `backend/voice/app/simulator_client.py` and `backend/voice/app/support_tools.py`; modify `config.py` (`SIMULATOR_BASE`, default `http://localhost:8090/v1`). Test: `tests/test_support_tools.py`.
- `SimulatorClient(settings, transport=None)` with `verify(mobile, dob, call_id) -> dict`. Each record method takes the session it holds and returns the JSON, or `{"error": CODE}` (no exceptions for 401, 403, 404, 422 or 423). It raises `ApiUnavailable` on connection errors.
- `SUPPORT_TOOL_SCHEMAS` and `run_support_tool(client, session_state, name, args) -> dict` for the tools:
  - `verify_customer`
  - `get_loan_applications`, `get_loans`, `get_schedule`
  - `get_accounts`, `get_transactions`
  - `get_tickets`, `get_ticket`, `create_service_request`, `register_complaint`
  - `get_policies`, `get_claims`
  - `search_faq`
  - `route_unsupported`, `escalate_to_human`
  - `end_call`
- Personal tools return `{"error": "NOT_VERIFIED", "note": "Ask for the registered mobile number and date of birth first."}` without calling the simulator when there is no session.
- Amounts get a `spoken` copy via `spoken_inr`.
- Tests:
  - no session means no HTTP call and `NOT_VERIFIED`;
  - verify, then `get_loans(type=vehicle)` returns `VL-31003`;
  - 403 maps to `NOT_YOUR_RECORD` with a note to decline;
  - three failures map to `LOCKED`, and personal tools keep refusing;
  - `search_faq` with empty items returns `{"no_approved_answer": true}`.

- [x] **A2: Support prompt, corrections, routing** (needs: A1)

**Files:** create `backend/voice/app/support_prompt.py`; modify `brain.py` to take the tool set from a `Mode` enum (`SUPPORT`, `RENEWAL`). Test: `tests/test_support_prompt.py` and `tests/test_brain.py`.
- The prompt rules:
  - speak only figures from tool results;
  - ask for the mobile number and date of birth before personal tools;
  - FAQ answers only from `search_faq`, and say "I don't have approved information on that" otherwise;
  - one clarifying question when the request is unclear;
  - read back ticket and complaint references digit by digit;
  - unsupported request: refuse briefly, then call `route_unsupported`, then offer what it can do;
  - unauthorised debit, fraud or a request for a human: `register_complaint` and/or `escalate_to_human`;
  - corrections ("no, my vehicle loan") re-query with the new loan type, without re-verifying.
- Brain tests with a scripted fake LLM:
  - the correction path calls `get_loans(type=vehicle)` after `get_loans(type=personal)`;
  - an unsupported request after a ticket calls `create_service_request`, then `route_unsupported`.

- [x] **A3: Parallel intent classifier** (needs: none)

**Files:** create `backend/voice/app/intents.py`. Test: `tests/test_intents.py`.
- `Intent` `StrEnum` (the 12 labels).
- `async classify(text, history_tail) -> IntentResult(intents: list[Intent], confidence: float, source: "llm"|"rules")`, using Groq `openai/gpt-oss-20b` in JSON mode (timeout 1.5 s), falling back to `rules_classify(text)` (keyword rules).
- It runs as `asyncio.create_task` on each final transcription, never awaited before the reply.
- Tests: the rules map the four EMI phrasings to `REPAYMENT`, "weather" to `UNSUPPORTED` and "the thing from last time" to `UNCLEAR`; a fake LLM timeout falls back to rules.

- [x] **A4: Spring V4: support calls and turn metadata** (needs: none)

**Files:**
- `backend/api/src/main/resources/db/migration/V4__support_calls.sql`: `calls.policy_id` nullable; add `kind` (`SUPPORT` | `RENEWAL`, default `RENEWAL`), `outcome` and `turns.meta jsonb`.
- A `support` package with `SupportController` at `/api/v1/support/calls`: POST start, POST `{id}/turns` with `{role, text, meta}`, POST `{id}/end` with `{outcome}`, GET `{id}`, GET list with `?outcome=`.

Tests (`SupportControllerTest`):
- start, then a turn with meta, then end, then GET returns the meta in order;
- the renewal tests still pass.

- [x] **A5: Voice records turn metadata; support calls** (needs: A1, A3, A4)

**Files:** modify `api_client.py`, `pipeline.py` and `main.py`.
- `POST /support/offer` (WebRTC) and `POST /support/text-call` start a `SUPPORT` call.
- Each customer turn posts `{intents, verified, verify_failures}`. Each agent turn posts `{tool_trace: [{name, args, result_summary}], retrieved: {...}, refs: [...]}`.
- Customer-turn intents are back-filled when the classifier finishes.
- Test: a text call through a fake LLM and mocked simulator posts the turns with that meta.

- [x] **A6: Speech front end tuned from the benchmark** (needs: none)

**Files:** create `backend/voice/app/speech.py`; modify `pipeline.py` and `config.py`.
- VAD params, pre-roll, the STT model, `prompt` and `language`, FLAC 16 kHz upload, and the invented-transcript filter, with the exact values from the report. Smart Turn and denoise only if the report supports them.
- `GROQ_API_KEYS` rotation on 429.
- Tests: noise-only audio yields no transcription frame; a phantom "Thank you." with high `no_speech_prob` is dropped; the domain prompt is sent.

- [x] **A7: Audio-file simulation** (needs: A5, A6)

**Files:** add `POST /sim/audio` to `main.py` (multipart, files in turn order, optional `call_id` to continue a call); create `backend/voice/scripts/simulate_audio.py <dir|files> [--out report.md]`.
- It uses the same `speech.py` path as live. It returns per turn `{transcript, intents, verified, tool_trace, retrieved, reply_text, reply_audio_b64}` and records a `SUPPORT` call in Spring.
- Tests: two WAV turns produce two transcripts and a call record; a silent file produces a turn marked `no_speech`, with no reply.

- [x] **A8: Operator panel** (needs: A4, A5)

**Files:** create `frontend/src/pages/SupportDesk.tsx` (route `/support`, the landing page) and `SupportCall.tsx`, with `api/support.ts`.
- **Live view:**
  - Start and End buttons;
  - the mic (reusing the Call.tsx WebRTC code);
  - an "Upload audio" tab calling `/sim/audio`;
  - the transcript stream;
  - an intent chip per customer turn;
  - a verified / not verified / locked badge;
  - a Retrieved card per agent turn (the tool name and the fields used);
  - the reply text.
- **Lists:** calls (with outcome); tickets, complaints, routed queries and escalations (simulator `/ops/records`).
- Tests (vitest): the panel renders the meta from a mocked call; the upload tab posts files.

- [x] **A9: Evaluation harness** (needs: A7, P2, P4)

**Files:** create `backend/voice/eval/run_scenarios.py [--full] [--accent in] [--condition clean]`.
- It resets the simulator, plays each scenario's rendered audio through `/sim/audio`, and checks `expect` and `outcome`.
- It writes `eval/out/report.md` with:
  - intent accuracy (overall, per accent, clean vs noisy);
  - ticket correctness;
  - refusal correctness;
  - disclosures before verification (must be 0);
  - latency p50/p95.
- The default is a sample, to protect the shared Groq quota.

- [x] **A10: Docs and demo** (needs: A9, C3, C4, C5, C6)
- README sections: the `/sim/audio` JSON, run steps for 4 services, accent/noise results from A9, and the demo script (which seed customer to use for each scenario).
- A fresh-database run-through of all 12 scenarios.

- [ ] **A11 (stretch): Renewal Desk handoff** (needs: A2, A10)
- `handoff_renewal` maps the simulator's insurance `policy_no` to the Spring renewal policy. The voice service creates the Spring renewal call pre-verified, passing the simulator verification, and switches `Mode` to `RENEWAL` in the same call.

---

## Level 2 (31 Oct): plan `docs/superpowers/plans/2026-10-31-l2-gaps-and-hindi.md`

Tasks L1 and L2 touch the simulator with Chirag's OK. Contract additions are listed in the main plan under "Shared contract: Level 2 (added 31 Oct)".

- [x] **L0: Save the Level 2 brief** (needs: none)
- `docs/brief/problem-05-level2.md`, verbatim from the challenge pack, the 7 capabilities as headings; AGENTS.md "Where things are" row.

- [x] **L1: Ticket statuses, department, progress and status updates (simulator)** (needs: L0)
- `TicketStatus` + `AWAITING_INFO`, `REJECTED`; `Department`; tickets carry `department`, `progress`, `eta_days`; `PATCH /v1/ops/tickets/{ref}`; seed SR-40103 (REJECTED), SR-40104 (AWAITING_INFO), SR-40105 (RESOLVED). Test: `tests/test_ticket_status.py`.

- [x] **L2: Complaint statement and reference, escalation category and linked records (simulator)** (needs: L0)
- Complaints keep `original_statement` and `related_ref`; escalations carry `category` (`EscalationCategory` + six values) and `related_refs`; both on `/ops/records`. Test: `tests/test_l2_records.py`.

- [x] **L3: Voice tools send the new fields; the agent explains ticket statuses** (needs: L1, L2)
- `register_complaint` sends the caller's last words and an optional `related_ref`; `escalate_to_human` sends its trigger as `category` and the call's refs as `related_refs`; REQUEST STATUS prompt rule. Test: `tests/test_l2_tools.py`.

- [x] **L4: Escalation backstops: verification lock and repeated misunderstanding** (needs: L3)
- `_escalate_if_stuck`: one `AUTH_LOCKED` hand-over when the call locks, one `REPEATED_MISUNDERSTANDING` after three `UNCLEAR` turns; a failed hand-over is never claimed. Test: `tests/test_escalation_backstops.py`.

- [x] **L5: Operation outcome per tool call, failed count per call** (needs: none)
- `OpOutcome` `OK|FAILED|DECLINED` on every `tool_trace` entry (voice) and `failedOps` on the call list (core API). Tests: `tests/test_op_outcome.py`, `backend/api/tests/test_support.py`.

- [x] **L6: Panel: statuses, failures, departments, statements, linked records, status control** (needs: L1, L2, L5)
- Status-toned ticket pills, department and progress, "N failed" pill, outcome pill per Retrieved card, complaint statement in quotes with its "About" ref, escalation ref pills, Save-based ticket status control (`PATCH /ops/tickets/{ref}`). Tests: `SupportDesk`, `SupportCall`, `CustomerCard`.

- [x] **H1: Hindi as a caller language** (needs: none)
- `SpeechLanguage.HINDI`, `hi-IN-SwaraNeural`, script detection with combining marks, Hindi STT prompt and fixed lines, greeting offers each enabled language, `VOICE_LANGUAGES=en,kn,hi`. Test: `tests/test_hindi.py`.

- [x] **H2: Hindi measured and in the scenario set** (needs: H1)
- Renderer voice `hi-IN-MadhurNeural`, accent `hi` in the harness, scenarios 15–16, `docs/stt-benchmark.md` § Hindi from a measured run (23 requests). The audio scenario run is still "Not run" there.

- [x] **T1: English translation of Kannada and Hindi turns (voice)** (needs: H1)
- `translate.to_english`, turn meta `text_en` and `language`, `VOICE_TRANSLATE_MODEL`; the reply never waits for it; `finish()` gives it 3 s. Test: `tests/test_translate.py`.

- [x] **T2: Panel: English beside Kannada and Hindi turns** (needs: T1)
- Language chip, English line under each translated turn, "English first" switch, search over `text_en`. Tests: `SupportCall`, `search`.

- [x] **L7: Demo script and docs** (needs: L1, L2, L3, L4, L5, L6, H1, H2, T1, T2)
- README Level 2 walk-through and Hindi/Kannada run steps; contract additions in the main plan; these rows.

- P1/P2 transcript redaction: on hold by owner decision, parked on branch `feat/pii-redaction` (not on `develop`).
- V1 (`fix/verification-capture`, hotfix to `develop` on its own): verification uses the caller's own mobile and date of birth, keeps a correctly heard value, re-asks only what is missing without spending an attempt; the README's step 5a depends on it.
