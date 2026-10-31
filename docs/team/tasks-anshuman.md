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

- [ ] **A10: Docs and demo** (needs: A9, C3, C4, C5, C6)
- README sections: the `/sim/audio` JSON, run steps for 4 services, accent/noise results from A9, and the demo script (which seed customer to use for each scenario).
- A fresh-database run-through of all 12 scenarios.

- [ ] **A11 (stretch): Renewal Desk handoff** (needs: A2, A10)
- `handoff_renewal` maps the simulator's insurance `policy_no` to the Spring renewal policy. The voice service creates the Spring renewal call pre-verified, passing the simulator verification, and switches `Mode` to `RENEWAL` in the same call.
