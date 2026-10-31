# CSM Voice Agent Level 2 Gaps, Hindi, English Transcripts and PII Redaction: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Teammates' agents: start at `AGENTS.md`.** Tasks L1–L2 touch `backend/simulator` (Chirag's service): get Chirag's OK or hand them to him.

**Goal:** Close the gaps between the current build and problem #05 Level 2, add Hindi as a third caller language beside English and Kannada, and keep personal data out of stored transcripts while letting an authorised person recover it.

The Level 2 gaps (audit of 31 Oct against `docs/brief/problem-05-level2.md`):
- **Ticket status tracking:** statuses REJECTED and AWAITING_INFO, an assigned department and a progress note.
- **Complaints:** the caller's original statement next to the structured summary, plus the account or transaction reference.
- **Escalation triggers:** escalate automatically after repeated authentication failure (lock) and after repeated misunderstanding.
- **Escalation records:** an issue category and the call's related service records.
- **Dashboard:** separate failed operations from successful and pending ones.

**Architecture:**
- **Simulator (port 8090):** gains the new record fields (SQLite columns via `ADDED_COLUMNS`) and an ops endpoint to move a ticket's status.
- **Voice service (port 7861):**
  - passes the new fields from its tools;
  - adds two escalation backstops beside the existing fraud and routing backstops;
  - tags every tool call with an operation outcome.
- **Core API (port 8080):** counts failed operations per call.
- **Panel:** shows statuses with tone, failures, departments, original statements and linked records.
- **Transcript PII redaction:** the core API redacts every turn it stores. Mobile numbers, dates of birth, Aadhaar, PAN, email, card and account numbers, and names in structured fields become tokens such as `[MOBILE#1]`. The real values go to a separate, encrypted vault database, so the transcript and the personal data are never stored together. An admin can reveal them, and every reveal is audited. Audio redaction is out of scope (later).
- **English transcript for Kannada and Hindi turns:** after a turn in Kannada or Hindi script is recorded (caller or agent), the voice service translates the text to English in the background with the small Groq model and patches it onto the turn's meta. The original stays the record. The panel shows the English beneath it. Rejected alternative: Whisper audio translation. It needs `whisper-large-v3` (not turbo), adds a second audio upload per segment, and cannot cover agent replies, which have no audio.
- **Hindi:** generalises the Kannada design. The call's language comes from the transcript's script; each language has its own Whisper prompt, voice and fixed lines.

**Tech Stack:** Python 3.12 FastAPI + SQLite (simulator, core API), Pipecat 1.12 + Groq Whisper + edge-tts (voice), React + TypeScript + Vitest (panel).

**Spec:**
- `docs/brief/problem-05-level2.md` (Task L0 saves it from the challenge pack, pages 23–24).
- The Kannada design in `docs/stt-benchmark.md` § "Kannada", which Hindi follows.

## Global Constraints
- Everything in `docs/superpowers/plans/2026-10-31-csm-voice-agent.md` § Global Constraints applies (no Anthropic keys, synthetic data, no hard-coded statistics, no compliance claims, `StrEnum` vocabularies with 422 on unknown values, PR into `develop`).
- **Shared contracts only grow.** Add fields, enum values and endpoints; never rename or remove existing ones. Every new response field is optional for readers.
- **"The agent must not claim that a request has been completed if the underlying API failed"** (brief §2): every backstop that raises a record checks for `"error"` before it gives a reference.
- **Tests per service:**
  - simulator: `cd backend/simulator && .venv/bin/python -m pytest -q <files>`;
  - voice: `cd backend/voice && .venv/bin/python -m pytest -q <files>`;
  - core API: `cd backend/api && .venv/bin/pytest -q <files>`;
  - panel: `cd frontend && npx vitest run <files> && npx tsc --noEmit`.
  - Run the named files, not the whole suite.

## Review Focus
1. **Hindi heard as Urdu script or romanised ("meri EMI kab hai").** The call stays English and keeps answering; it never switches to a Hindi voice for text it cannot show in Devanagari. Test: H1 `test_romanised_or_urdu_hindi_keeps_the_call_english`.
2. **Code-mixed Hindi with English bank words ("मेरा loan statement चाहिए").** The call switches to Hindi even though Latin letters outnumber Devanagari. Test: H1 `test_code_mixed_hindi_switches_the_call`.
3. **The caller keeps trying after verification locks.** Exactly one AUTH_LOCKED escalation per call, however many more attempts follow. Test: L4 `test_lock_escalates_once`.
4. **Personal data said in a form the patterns don't expect** (spaced "98765 00002", "+91 98765-00002", digit words "nine eight seven six five zero zero zero zero two", "3rd of November 1985") while bank references (SR-40102, TXN-88213), amounts (₹12,450) and due dates this year survive untouched. Test: P1 `test_redaction_catches_spoken_and_spaced_forms_and_keeps_bank_references`.
5. **A backstop escalation while the simulator is down.** No reference is spoken, and the tool trace shows outcome FAILED. Test: L4 `test_backstop_escalation_failure_is_not_claimed`.

---

### Task L0: Save the Level 2 brief

**Files:**
- Create: `docs/brief/problem-05-level2.md`: the "Level 2: Execute Service Requests, Manage Conversations and Escalate Issues" section of `Hackathon_Challenge_Pack_Level1_Level2_8058.pdf`, verbatim, with the 7 capabilities as headings.

- [ ] **Step 1:** Write the file; add a row to the AGENTS.md "Where things are" table: `docs/brief/problem-05-level2.md | What the judges test at Level 2`.
- [ ] **Step 2: Commit** `docs: Level 2 brief for problem 05`

### Task L1: Ticket statuses, department, progress and status updates (simulator)

**Files:**
- Modify: `backend/simulator/app/enums.py`, `backend/simulator/app/store.py`, `backend/simulator/app/routers/csm.py`, `backend/simulator/app/routers/ops.py`, `backend/simulator/data/seed/tickets.json`
- Test: `backend/simulator/tests/test_ticket_status.py` (new), update `tests/test_csm.py::test_create_and_read_ticket` field set

**Interfaces:**
- Produces:
  - `TicketStatus` gains `REJECTED = "REJECTED"` and `AWAITING_INFO = "AWAITING_INFO"`.
  - `Department(StrEnum)`: `ACCOUNT_SERVICES = "Account Services"`, `LOAN_SERVICING = "Loan Servicing"`, `KYC_RECORDS = "KYC & Records"`, `CUSTOMER_SERVICE = "Customer Service"`.
  - `TICKET_DEPARTMENT: dict[TicketCategory, Department]` maps STATEMENT→ACCOUNT_SERVICES, REPAYMENT_SCHEDULE→LOAN_SERVICING, ACCOUNT_DOCUMENT→ACCOUNT_SERVICES, ADDRESS_CHANGE→KYC_RECORDS, OTHER→CUSTOMER_SERVICE.
  - The ticket view (`TICKET_FIELDS`) adds `department`, `progress`, `eta_days`.
  - `Route.OPS_TICKET = "/ops/tickets/{ref}"`: `PATCH {status: TicketStatus, progress: str | None}` (ops Basic auth) returns the ticket view; 404 for an unknown ref; 422 for an unknown status.
  - `BankStore.update_ticket(ref: str, status: TicketStatus, progress: str | None) -> dict | None` covers both SQLite tickets and seed tickets. Seed tickets change in memory; `/ops/reset` restores them.
  - `/ops/records` ticket items and the `/ops/customers/{ref}` ticket entries carry `department` and `progress`.

- [ ] **Step 1: Write the failing tests** in `tests/test_ticket_status.py`:
  - `test_new_ticket_has_department_and_progress`: a STATEMENT ticket has `department == "Account Services"`, a non-empty `progress` and an `eta_days` equal to `settings.ticket_eta_days`.
  - `test_ops_can_move_a_ticket_to_each_status`: PATCH SR-40200 through `AWAITING_INFO` (with progress "Waiting for the delivery address"), `REJECTED` and `RESOLVED`. After each PATCH, `GET /v1/csm/tickets/SR-40200` as CUST-1002 shows that status and progress.
  - `test_seed_ticket_update_is_undone_by_reset`: PATCH SR-40102 to RESOLVED, `POST /v1/ops/reset`, and it reads IN_PROGRESS again.
  - `test_ticket_update_needs_ops_and_a_known_status_and_ref`: 401 without auth; 422 for `status: "LOST"`; 404 for SR-99999.
  - `test_seed_has_each_open_and_closed_status`: seed tickets include `REJECTED` SR-40103 (CUST-1003, ADDRESS_CHANGE, progress "Rejected: the address proof was unreadable. Please submit a clear copy."), `AWAITING_INFO` SR-40104 (CUST-1004, ACCOUNT_DOCUMENT, progress "Waiting for the customer to confirm the delivery address.") and `RESOLVED` SR-40105 (CUST-1005, STATEMENT, progress "Statement sent to the registered email address.").
- [ ] **Step 2:** Run them; expect FAIL (no department, no route).
- [ ] **Step 3:** Implement:
  - add `progress TEXT` and `department TEXT` to `ADDED_COLUMNS["tickets"]`;
  - `create_ticket` sets the department from `TICKET_DEPARTMENT` and the progress "Received by the {department} team.";
  - seed tickets get their department from the map and keep the seed progress;
  - add the PATCH route and the three new seed rows. Existing SR-40102 gets progress "With the Account Services team.".
- [ ] **Step 4:** Run `tests/test_ticket_status.py tests/test_csm.py tests/test_store.py tests/test_ops_customer.py`; expect PASS. Fix count assertions that include seed tickets.
- [ ] **Step 5:** Re-run `scripts/build-verification-lab.py` so `docs/verification-lab.*` lists the new tickets.
- [ ] **Step 6: Commit** `feat(simulator): ticket statuses REJECTED/AWAITING_INFO, department, progress, ops status update`

### Task L2: Complaint statement and reference, escalation category and linked records (simulator)

**Files:**
- Modify: `backend/simulator/app/enums.py`, `app/store.py`, `app/routers/csm.py`
- Test: `backend/simulator/tests/test_l2_records.py` (new)

**Interfaces:**
- Produces:
  - `ComplaintRequest` adds `original_statement: str | None = None` and `related_ref: str | None = None` (an account, loan or transaction reference). `description` stays the structured summary.
  - `EscalationCategory(StrEnum)`: `CUSTOMER_REQUEST`, `DISSATISFIED`, `UNRESOLVED`, `SENSITIVE`, `AUTH_LOCKED`, `REPEATED_MISUNDERSTANDING`, with the same strings as the names.
  - `EscalationRequest` adds `category: EscalationCategory | None = None` and `related_refs: list[str] = []`.
  - `ADDED_COLUMNS`: `complaints: {original_statement: TEXT, related_ref: TEXT}`; `escalations: {related_refs: TEXT}` (JSON list; `category` already exists).
  - `/ops/records` items add `original_statement` (complaints, else null), `related_ref` (complaints) and `related_refs` (escalations, else null). `get_complaints` entries add `original_statement` and `related_ref`.

- [ ] **Step 1: Write the failing tests:**
  - `test_complaint_keeps_the_callers_words_and_reference`: POST a complaint with description "Failed NEFT transfer, no reason recorded", `original_statement` "my fifteen thousand transfer to Rajesh failed yesterday" and `related_ref` "TXN-88213". The ops record and the customer profile both show all three.
  - `test_escalation_has_category_and_linked_records`: POST an escalation with `category: "UNRESOLVED"` and `related_refs: ["SR-40200", "CMP-50200"]`. The ops escalation record returns the category and the list in order.
  - `test_escalation_without_new_fields_still_works`: the old body shape gives 201, with `category` and `related_refs` null or empty.
  - `test_unknown_escalation_category_is_422`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement the request fields and columns; extend `create_complaint(..., original_statement=None, related_ref=None)` and `create_escalation(..., related_refs=None)`; extend `list_records` and `get_complaints`.
- [ ] **Step 4:** Run `tests/test_l2_records.py tests/test_csm.py tests/test_records.py`; expect PASS.
- [ ] **Step 5: Commit** `feat(simulator): complaint original statement and reference, escalation category and linked records`

### Task L3: Voice tools send the new fields; the agent explains ticket statuses

**Files:**
- Modify: `backend/voice/app/support_tools.py`, `app/simulator_client.py`, `app/support_brain.py` (one line), `app/support_prompt.py`, `app/vocab.py`
- Test: `backend/voice/tests/test_l2_tools.py` (new)

**Interfaces:**
- Consumes: the L1 ticket view fields and the L2 request fields.
- Produces:
  - `CallSession.last_caller_text: str = ""`, set by `SupportBrain.reply` before `_loop()`.
  - `SimulatorClient.complaint(session, category, description, severity, call_id, original_statement=None, related_ref=None)`.
  - `SimulatorClient.escalation(session, reason, summary, call_id, category=None, related_refs=None)`.
  - The `register_complaint` schema adds an optional `related_ref` ("account, loan or transaction reference the complaint is about, e.g. TXN-88213").
  - The `escalate_to_human` tool sends `category = trigger` and `related_refs = list(call.refs)`.
  - `EscalationTrigger` gains `AUTH_LOCKED` and `REPEATED_MISUNDERSTANDING`; these two are not offered in the tool schema enum, because only the backstops (L4) use them.

- [ ] **Step 1: Write the failing tests** (MockTransport simulator, as in `tests/test_support_tools.py`):
  - `test_complaint_sends_the_callers_words_and_reference`: after the brain hears "my fifteen thousand transfer failed" and the model calls `register_complaint` with `related_ref` "TXN-88213", the POST body has `original_statement` equal to that sentence and `related_ref` "TXN-88213".
  - `test_escalation_sends_trigger_as_category_and_the_calls_refs`: with `call.refs == ["SR-40200"]`, the escalation body has `category` "UNRESOLVED" and `related_refs` ["SR-40200"].
  - `test_tool_schema_does_not_offer_backstop_triggers`: the `escalate_to_human` trigger enum excludes AUTH_LOCKED and REPEATED_MISUNDERSTANDING.
  - `test_prompt_tells_the_agent_how_to_report_ticket_status`: `support_prompt()` contains "AWAITING_INFO" and "REJECTED".
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement. Add this prompt rule after "SERVICE REQUESTS", as copy:
  `"REQUEST STATUS: give the status, the department and the progress note in plain words. OPEN or IN_PROGRESS: say it is being worked on and offer a follow-up. AWAITING_INFO: say what the bank is waiting for, from the progress note. REJECTED: give the reason from the progress note and offer to raise a new request. RESOLVED or CLOSED: say it is done. If a request is unresolved and the caller is unhappy, offer to escalate."`
- [ ] **Step 4:** Run `tests/test_l2_tools.py tests/test_support_tools.py tests/test_support_brain.py tests/test_prompt.py`; expect PASS.
- [ ] **Step 5: Commit** `feat(voice): complaint statement and reference, escalation category and linked records, ticket status rule`

### Task L4: Escalation backstops: verification lock and repeated misunderstanding

**Files:**
- Modify: `backend/voice/app/support_brain.py`, `app/support_tools.py` (CallSession field)
- Test: `backend/voice/tests/test_escalation_backstops.py` (new)

**Interfaces:**
- Consumes: L3 `SimulatorClient.escalation(..., category, related_refs)` and the new `EscalationTrigger` values.
- Produces:
  - `CallSession.unclear_streak: int = 0`.
  - `UNCLEAR_BEFORE_ESCALATION = 3` in `support_brain.py`.
  - `SupportBrain._escalate_if_stuck(turn: SupportTurn) -> bool`. It runs after intents are known. It raises one escalation when (a) `call.locked` became True this turn, or (b) `unclear_streak` reached 3. It runs the tool through the same path as `_act_on_fraud_if_missed`, so the escalation is in `turn.tool_calls` and `call.refs`.
  - No escalation if the call already has an `ESC-` ref.
  - When it ran, `reply()` calls `_loop()` again so the spoken reply carries the reference or the failure. The assistant message is appended to history only after the backstops.
  - Streak rule: a customer turn whose intents are exactly `[UNCLEAR]` adds 1; any other intent resets it to 0; `no_speech` turns leave it unchanged.

- [ ] **Step 1: Write the failing tests** (Scripted LLM + FakeSimulator from the existing tests):
  - `test_lock_escalates_once`: three wrong verifications lock the call, giving one escalation with category AUTH_LOCKED and summary "Verification locked after 3 failed attempts". A fourth attempt adds none.
  - `test_three_unclear_turns_escalate_with_repeated_misunderstanding`: three turns classified `[UNCLEAR]` give one escalation with category REPEATED_MISUNDERSTANDING, and the final reply text includes the ESC reference.
  - `test_misunderstanding_streak_ignores_no_speech_and_resets_on_understanding`: the sequence UNCLEAR, no-speech, UNCLEAR, REPAYMENT, UNCLEAR, UNCLEAR produces no escalation.
  - `test_backstop_escalation_failure_is_not_claimed`: when the simulator returns 503, the reply contains no "ESC-" and the trace result has `"error"`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement `_escalate_if_stuck` and the streak update in `reply()`; reuse the backstop tool-call message shape from `_act_on_fraud_if_missed`.
- [ ] **Step 4:** Run `tests/test_escalation_backstops.py tests/test_support_brain.py tests/test_turn_gate.py`; expect PASS.
- [ ] **Step 5: Commit** `feat(voice): escalate on verification lock and repeated misunderstanding`

### Task L5: Operation outcome per tool call, failed count per call

**Files:**
- Modify: `backend/voice/app/vocab.py`, `app/support_brain.py`, `backend/api/app/vocab.py`, `backend/api/app/services/support.py`
- Test: `backend/voice/tests/test_op_outcome.py` (new), `backend/api/tests/test_support.py` (add one test)

**Interfaces:**
- Produces:
  - Voice `OpOutcome(StrEnum)`: `OK`, `FAILED`, `DECLINED`.
  - `op_outcome(result: dict) -> OpOutcome` beside `summarise()`:
    - no `"error"` → OK;
    - `error` in {SYSTEM_UNAVAILABLE, BAD_ARGUMENTS, UNKNOWN_TOOL} or `HTTP_5xx` → FAILED;
    - any other error (NOT_VERIFIED, LOCKED, NOT_YOUR_RECORD, VERIFICATION_FAILED, ASK_FIRST, HTTP_4xx) → DECLINED.
  - Every `tool_trace` entry gains `"outcome"`.
  - Core API: the `GET /support/calls` list items add `failedOps: int`, the count of trace entries with outcome FAILED. The API's `OpOutcome` constant has the same values.

- [ ] **Step 1: Write the failing tests:**
  - `test_op_outcome_classifies_results`: covers each branch above, including `{"error": "HTTP_503"}` → FAILED and `{"error": "HTTP_404"}` → DECLINED.
  - `test_trace_entries_carry_outcome`: a brain turn with one OK call and one SYSTEM_UNAVAILABLE call records outcomes `["OK", "FAILED"]`.
  - API `test_call_list_counts_failed_operations`: a call whose transcript has 2 FAILED entries and 1 OK lists `failedOps == 2`; a call without outcomes lists 0.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `backend/voice tests/test_op_outcome.py tests/test_support_brain.py` and `backend/api tests/test_support.py`; expect PASS.
- [ ] **Step 5: Commit** `feat: operation outcome on every tool call, failed count per call`

### Task L6: Panel: statuses, failures, departments, statements, linked records, status control

**Files:**
- Modify: `frontend/src/vocab.ts`, `src/api/support.ts`, `src/api/mockSupport.ts`, `src/api/paths/simulator.ts`, `src/pages/SupportDesk.tsx`, `src/pages/SupportCall.tsx` (Retrieved card), `src/components/CustomerCard.tsx`
- Test: `src/pages/SupportDesk.test.tsx`, `src/pages/SupportCall.test.tsx`, `src/components/CustomerCard.test.tsx`

**Interfaces:**
- Consumes: L1 PATCH route and fields, L2 record fields, L5 `outcome` and `failedOps`.
- Produces:
  - `TicketStatus` and `OpOutcome` const objects in `vocab.ts`.
  - `opsTicketPath(ref)` in `paths/simulator.ts`.
  - `updateTicket(ref: string, status: TicketStatus, progress: string | null): Promise<OpsRecord>`.
  - `OpsRecord` adds `department?`, `progress?`, `original_statement?`, `related_ref?`, `related_refs?`.
  - `ToolTrace.outcome?: OpOutcome`; `SupportCallSummary.failedOps?: number`.
  - `RECORD_STATUS_TONE: Record<string, string>`: OPEN→`warn`, IN_PROGRESS→`info`, AWAITING_INFO→`warn`, RESOLVED→`ok`, CLOSED→`ok`, REJECTED→`bad`.

- [ ] **Step 1: Write the failing tests:**
  - Desk: a call with `failedOps: 2` shows a `bad` pill "2 failed"; the Tickets tab colours REJECTED `bad` and AWAITING_INFO `warn` and shows the department and progress.
  - Desk: choosing "Awaiting info" in a ticket row's status select, with progress text, calls `updateTicket('SR-40200', 'AWAITING_INFO', '<text>')` and refreshes the row.
  - Desk: an escalation row shows its related refs as ref pills; a complaint row shows the original statement in quotes.
  - Call screen: a Retrieved row with outcome FAILED shows a "Failed" `bad` pill, and DECLINED shows a "Declined" `dim` pill.
  - CustomerCard: a ticket shows department and progress; a complaint shows its original statement.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; mock mode mirrors each new field and `updateTicket`.
- [ ] **Step 4:** Run `npx vitest run src/pages/SupportDesk.test.tsx src/pages/SupportCall.test.tsx src/components/CustomerCard.test.tsx && npx tsc --noEmit`; expect PASS.
- [ ] **Step 5: Commit** `feat(panel): ticket status tones and control, failed operations, complaint statements, escalation links`

### Task H1: Hindi as a caller language

**Files:**
- Modify: `backend/voice/app/vocab.py`, `app/speech.py`, `app/support_pipeline.py`, `app/support_prompt.py`, `app/intents.py`, `app/config.py` (doc only), `.env.example`
- Test: `backend/voice/tests/test_hindi.py` (new); keep `tests/test_kannada.py` and `tests/test_pause.py` green

**Interfaces:**
- Produces:
  - `SpeechLanguage.HINDI = "hi"`. `VOICE_LANGUAGES=en,kn,hi` enables all three.
  - `speech.py`:
    - `VOICES: dict[SpeechLanguage, str]` = {KANNADA: "kn-IN-SapnaNeural", HINDI: "hi-IN-SwaraNeural"}. `KANNADA_VOICE` stays as an alias.
    - `CODE_MIX_SHARE = 0.3`.
    - `script_language(text: str | None) -> SpeechLanguage | None`: KANNADA or HINDI when that script (Kannada `[ಀ-೿]`, Devanagari `[ऀ-ॿ]`) makes up at least `CODE_MIX_SHARE` of the letters; ENGLISH when there are letters but neither script does; None when there are no letters.
    - `CallLanguage.heard()` switches to `script_language(text)` only if that language is enabled.
    - `stt_prompt()` returns the current language's prompt once the call is Kannada or Hindi. Otherwise it returns `MULTILINGUAL_PROMPT`: the English domain prompt plus the Kannada and/or Hindi words of the enabled languages.
    - `HINDI_PROMPT = "बैंक ग्राहक कॉल। EMI, लोन, खाता, स्टेटमेंट, किस्त, NACH, KYC, SR-40102."`.
    - `is_mostly_hindi(text) -> bool`, the same rule as `is_mostly_kannada`.
    - `voice_for(text, default, call)` picks `VOICES[lang]` when the reply is mostly in that script or the call is in that language.
    - `normalise_refs` also maps Devanagari digits `०-९` to `0-9`.
  - `support_pipeline.py`:
    - `HINDI_LINES` (same keys as `KANNADA_LINES`).
    - `LINES: dict[SpeechLanguage, dict[str, str]]`.
    - `SupportResponder.line()` uses `LINES.get(language.current)`.
    - After `GREETING`, the greeting queues one line per enabled non-English language: `GREETING_KANNADA`, then `GREETING_HINDI = "आप हिंदी में भी बात कर सकते हैं।"`.
  - `support_prompt.py`:
    - `language_rule(languages) -> str` builds the LANGUAGE rule from the enabled languages. The Hindi part: "Hindi in Devanagari script (Hindi-English mixing is fine)", with Hindi number words शून्य 0, एक 1, दो 2, तीन 3, चार 4, पाँच 5, छह 6, सात 7, आठ 8, नौ 9.
    - `support_prompt()` uses it instead of `LANGUAGE_RULE`. The `LANGUAGE_RULE` constant stays, equal to the en+kn rule.
  - `intents.py`: the classifier prompt adds Hindi examples: "मेरी अगली EMI कब है?" is REPAYMENT; "मुझे लोन स्टेटमेंट चाहिए" is SERVICE_REQUEST; Hindi digit words giving a mobile number or date of birth are IDENTITY.
  - `HINDI_LINES` copy (female voice, so feminine verb forms):
    - FALLBACK: "माफ़ कीजिए, मैं ठीक से सुन नहीं पाई। क्या आप दोबारा बता सकते हैं?"
    - SYSTEM_DOWN: "माफ़ कीजिए, हमारे सिस्टम से जुड़ने में दिक्कत हो रही है। कृपया थोड़ी देर रुकें या कुछ देर बाद फिर कोशिश करें।"
    - STILL_THERE: "क्या आप अभी भी लाइन पर हैं?"
    - NOISY_ASK: "माफ़ कीजिए, पीछे से कुछ शोर आ रहा है। क्या आप दोबारा बता सकते हैं?"
    - IDLE_GOODBYE: "मुझे कुछ सुनाई नहीं दिया, इसलिए मैं अब कॉल समाप्त कर रही हूँ। अज़ेंटियो डेमो बैंक को कॉल करने के लिए धन्यवाद।"

- [ ] **Step 1: Write the failing tests** in `tests/test_hindi.py`:
  - `test_hindi_call_switches_and_back`: `CallLanguage((EN, KN, HI))` hears "मेरी अगली EMI कब है" and becomes HINDI, then "when is my EMI" and becomes ENGLISH, then "ನನ್ನ ಸಾಲದ ಕಂತು" and becomes KANNADA.
  - `test_code_mixed_hindi_switches_the_call`: "मेरा loan statement चाहिए" gives HINDI.
  - `test_romanised_or_urdu_hindi_keeps_the_call_english`: "meri EMI kab hai" and "میری EMI کب ہے" both leave `current == ENGLISH`.
  - `test_hindi_not_enabled_stays_english`: `CallLanguage((EN, KN))` hearing Devanagari stays ENGLISH.
  - `test_hindi_reply_gets_the_hindi_voice`: `voice_for("आपकी अगली EMI ₹12,450 है।", default)` returns "hi-IN-SwaraNeural".
  - `test_devanagari_digits_become_ascii`: `normalise_refs("मेरा नंबर ९८७६५००००२")` returns "मेरा नंबर 9876500002".
  - `test_fixed_lines_follow_a_hindi_call`: every `HINDI_LINES` value `is_mostly_hindi`, and `line(STILL_THERE)` is the Hindi copy on a Hindi call.
  - `test_greeting_offers_each_enabled_language`: en,kn,hi queues `[GREETING, GREETING_KANNADA, GREETING_HINDI]`; en,hi queues `[GREETING, GREETING_HINDI]`.
  - `test_stt_prompt_follows_the_call`: before any speech the prompt contains both "ಬ್ಯಾಂಕ್" and "बैंक"; on a Hindi call it is `HINDI_PROMPT`.
  - `test_prompt_language_rule_names_only_enabled_languages`: en,hi mentions Hindi and not Kannada.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement. Keep the existing public names (`is_mostly_kannada`, `KANNADA_VOICE`, `KANNADA_LINES`, `LANGUAGE_RULE`, `BILINGUAL_PROMPT`) so current tests and imports still work.
- [ ] **Step 4:** Run `tests/test_hindi.py tests/test_kannada.py tests/test_pause.py tests/test_speech.py tests/test_prompt.py tests/test_intents.py`; expect PASS.
- [ ] **Step 5:** In `.env.example`, document `VOICE_LANGUAGES=en,kn,hi` (the default stays `en`).
- [ ] **Step 6: Commit** `feat(voice): Hindi as a caller language`

### Task H2: Hindi measured and in the scenario set

**Files:**
- Modify: `backend/voice/eval/audio/render.py` (voices: `"hi": "hi-IN-MadhurNeural"`), `backend/voice/eval/run_scenarios.py` (`ACCENTS` adds `"hi"`), `docs/stt-benchmark.md` (new "Hindi" section)
- Create: `backend/voice/eval/scenarios/15-hindi-repayment.yaml`, `16-hindi-statement.yaml` (mirroring 13 and 14: CUST-1002, the same expectations, Hindi lines in Devanagari)
- Test: `backend/voice/tests/test_hindi.py::test_renderer_and_harness_accept_hindi` (same shape as the Kannada one)

- [ ] **Step 1:** Write the renderer/harness test; run it and expect FAIL; add the voice, accent and scenarios; run it and expect PASS.
- [ ] **Step 2: Measure** (uses Groq quota, not Anthropic). Render 5 Hindi clips (pure Hindi, code-mixed, digits, date of birth, a reference) and transcribe them with (a) auto plus the multilingual prompt, (b) auto plus `HINDI_PROMPT`, (c) pinned `hi`. Record WER, the script of each output and the detected language in `docs/stt-benchmark.md` § "Hindi", in the format of the Kannada table. Also re-run the 5 English clips with en,kn,hi to record the English cost.
- [ ] **Step 3:** If (a) writes Hindi in Urdu or Latin script more often than (b), make `MULTILINGUAL_PROMPT` lead with the Hindi words and re-measure. Record the decision under the table.
- [ ] **Step 4:** Run `eval/run_scenarios.py --only 15,16 --accent hi` against running services; paste the result into the benchmark section.
- [ ] **Step 5: Commit** `test(voice): Hindi benchmark and scenarios 15-16`

### Task L7: Demo script and docs

**Files:**
- Modify: `README.md` (demo script), `docs/team/tasks-anshuman.md` (task rows for L0–L7, H1, H2 with `needs:`), `docs/superpowers/plans/2026-10-31-csm-voice-agent.md` § Shared contract (append the new fields, routes and enum values under "added 31 Oct, Level 2")

- [ ] **Step 1:** Add the Level 2 demo walk-through to the README, one line per capability:
  1. multi-turn on CUST-1002;
  2. statement request, giving SR-…;
  3. status of SR-40104 (awaiting info), then the operator marks it RESOLVED live and the caller asks again;
  4. failed-transfer complaint for CUST-1004, giving CMP-… with the caller's words;
  5. three wrong verifications, giving the AUTH_LOCKED escalation;
  6. transcript correction on the call screen, then the stored transcript showing `[MOBILE#1]`, and the admin revealing it (audited);
  7. dashboard failed/pending pills.

  Then a Hindi and a Kannada call, with the English shown beside each turn.
- [ ] **Step 2:** Update the contract section and task rows.
- [ ] **Step 3: Commit** `docs: Level 2 demo script, contract additions, task rows`

### Task T1: English translation of Kannada and Hindi turns (voice)

**Files:**
- Create: `backend/voice/app/translate.py`
- Modify: `backend/voice/app/vocab.py` (`MetaKey.TEXT_EN = "text_en"`, `MetaKey.LANGUAGE = "language"`), `app/config.py` (`translate_model`, env `VOICE_TRANSLATE_MODEL`, default `"openai/gpt-oss-20b"`), `app/support_brain.py`, `app/main.py` (pass the translator in `State.new_support_brain`)
- Test: `backend/voice/tests/test_translate.py` (new)

**Interfaces:**
- Consumes: `script_language()` from H1 if it has landed; otherwise `is_mostly_kannada()`. T1 must not wait for H1: it translates Kannada now, and Hindi as soon as H1 adds the script.
- Produces:
  - `translate.py`: `async def to_english(text: str, *, api_key: str, model: str, transport: httpx.AsyncBaseTransport | None = None) -> str | None`, one Groq chat completion with temperature 0.
  - The system prompt, as copy: `"Translate this utterance from a bank customer-service call into English. Keep every number, amount, date and reference (for example SR-40102, ₹12,450) exactly as written. Output only the translation."`
  - It returns None on any HTTP error or empty output, and never raises.
  - `SupportBrain(..., translator: Callable[[str], Awaitable[str | None]] | None = None)`. After `_record` (customer turn) and the agent `_record`, when the text's script is Kannada or Hindi, it starts a background task in `self._pending`. The task calls the translator and then `_patch(seq, {MetaKey.TEXT_EN: en, MetaKey.LANGUAGE: "kn" | "hi"})`.
  - English turns are never sent to the translator. The reply path never waits for a translation.
  - `finish()` waits at most `TRANSLATE_GRACE_SECS = 3` for pending translations before ending the call. Later patches still land, because `patch_meta` is allowed after the call ends.
  - Ordering with P1: the English text passes through the API's redaction like any meta, so no extra work is needed.

- [ ] **Step 1: Write the failing tests** in `tests/test_translate.py`:
  - `test_kannada_customer_and_agent_turns_get_english`: with a fake translator returning "When is my next EMI?", a turn "ನನ್ನ ಮುಂದಿನ EMI ಯಾವಾಗ?" and an agent reply in Kannada give two `patch_meta` calls with `text_en` and `language: "kn"`.
  - `test_english_turns_are_not_translated`: the translator is never called for "when is my EMI".
  - `test_translation_failure_leaves_the_turn_alone`: a translator returning None (or raising) leaves no `text_en` patch, and the reply text is unchanged.
  - `test_reply_does_not_wait_for_translation`: with a translator that sleeps 0.5 s, `brain.reply()` returns in under 0.3 s.
  - `test_to_english_keeps_references_and_handles_errors`: MockTransport returning `{"choices":[{"message":{"content":"Your request SR-40102 is in progress."}}]}` gives that text, and a 500 gives None.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `tests/test_translate.py tests/test_support_brain.py tests/test_kannada.py tests/test_sim_audio.py`; expect PASS.
- [ ] **Step 5: Commit** `feat(voice): English translation of Kannada and Hindi turns on the record`

### Task T2: Panel: English beside Kannada and Hindi turns

**Files:**
- Modify: `frontend/src/api/support.ts` (`TurnMeta.text_en?: string`, `TurnMeta.language?: string`), `src/api/mockSupport.ts` (one Kannada sample turn with `text_en`), `src/pages/SupportCall.tsx`, `src/search.ts`
- Test: `src/pages/SupportCall.test.tsx`, `src/search.test.tsx`

**Interfaces:**
- Consumes: T1 meta keys.
- Produces:
  - A turn with `meta.text_en` shows a language chip ("Kannada" or "Hindi") and the English beneath the original in muted text, labelled "English".
  - A call-level toggle, "English first", swaps which line is prominent. It is held in state only.
  - `turnMatches` also searches `text_en`.

- [ ] **Step 1: Write the failing tests:**
  - A Kannada turn shows the "Kannada" chip and "English: When is my next EMI?".
  - "English first" puts the English line first.
  - Searching "EMI" matches a turn whose only English text is in `text_en`.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement. With P2, render `text_en` through `PiiText` too.
- [ ] **Step 4:** Run `npx vitest run src/pages/SupportCall.test.tsx src/search.test.tsx && npx tsc --noEmit`; expect PASS.
- [ ] **Step 5: Commit** `feat(panel): English beside Kannada and Hindi turns`

### Task P1: Transcript PII redaction with an encrypted vault (core API)

**Files:**
- Create: `backend/api/app/pii.py` (detection and tokenising), `backend/api/app/pii_vault.py` (the separate encrypted store)
- Modify: `backend/api/app/vocab.py`, `app/config.py`, `app/services/support.py` (`add_turn`, `patch_meta`, the feedback `correction`), `app/routers/support.py`, `requirements.txt` (`cryptography==43.0.3`), `.env.example` (`PII_VAULT_KEY`, `PII_VAULT_PATH`)
- Test: `backend/api/tests/test_pii.py` (new)

**Interfaces:**
- Produces:
  - `PiiKind(StrEnum)`: `MOBILE`, `DOB`, `AADHAAR`, `PAN`, `EMAIL`, `CARD`, `ACCOUNT_NUMBER`, `DIGITS`, `NAME`.
  - `pii.py`:
    - `redact_text(text: str, today: date) -> tuple[str, list[Found]]`, with `Found(kind: PiiKind, value: str, start: int, end: int)`.
    - `Redactor(vault: PiiVault, call_id: str)`. Its method `redact(value: Any) -> Any` walks strings, lists and dicts (the turn text and the whole `meta`, including `tool_trace` args and `retrieved` results), stores each value in the vault and returns the structure with tokens in place.
    - Within one call the same value always gets the same token.
  - Token format: `[KIND#n]`, numbered per call and kind in order of first appearance.
  - Detection rules:
    - MOBILE: an Indian 10-digit mobile starting 6–9, optionally prefixed by `+91`, `91` or `0`, with optional one space or hyphen inside.
    - DOB: a date whose year is at least 16 years before `today`, in the forms `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`, "3 November 1985", "3rd of November 1985" and "November 3, 1985". Due dates and other recent dates are kept.
    - AADHAAR: 12 digits not starting 0 or 1, optionally grouped 4-4-4.
    - PAN: `[A-Z]{5}[0-9]{4}[A-Z]`.
    - EMAIL.
    - CARD: 13–19 digits that pass the Luhn check, optionally grouped.
    - ACCOUNT_NUMBER: any other run of 9–18 digits.
    - DIGITS: 6 or more consecutive spoken digit words (zero/oh to nine, double/triple X).
    - NAME: the value of any dict key `first_name`, `last_name` or `name`.
    - Kept as they are: bank references (`SR-`, `CMP-`, `TXN-`… plus digits), masked numbers (`••• 4012`) and amounts.
  - `pii_vault.py`:
    - `PiiVault(path: Path, key: str | None)` is its own SQLite file (`PII_VAULT_PATH`, default `data/pii_vault.db`), separate from the calls database. Table `pii_values(call_id, token, kind, value_hmac, ciphertext, created_at)`.
    - Each value is encrypted on its own with Fernet under `PII_VAULT_KEY`; `value_hmac` (HMAC-SHA256 of the call id, kind and value) gives dedupe without storing plaintext.
    - `put(call_id, kind, value) -> token`, `get_all(call_id) -> dict[str, dict]` (`{token: {"kind", "value"}}`), `delete_call(call_id)`.
    - With no `PII_VAULT_KEY`, `put` still returns a token but stores no value (redaction never switches off), and the API logs one warning at startup.
  - Route `GET /support/calls/{call_id}/pii`: admin only (`require(Role.ADMIN)`; 403 for reviewer and analyst). Returns `{"tokens": {token: {kind, value}}}`. Each call writes an audit entry `PII_REVEALED` with the actor and the call id.
  - The calls DB and every API response other than this route hold only tokens.

- [ ] **Step 1: Write the failing tests** in `tests/test_pii.py`:
  - `test_turn_text_and_meta_are_stored_redacted`: POST a turn "My number is 98765 00002 and I was born on 3rd November 1985", with meta `tool_trace[0].args {"mobile": "9876500002", "date_of_birth": "1985-11-03"}` and `retrieved.verify_customer.customer.first_name "Rahul"`. The stored transcript (read straight from the calls DB) contains `[MOBILE#1]`, `[DOB#1]` and `[NAME#1]`, and none of "98765", "9876500002", "1985" or "Rahul". The args' mobile is the same `[MOBILE#1]`.
  - `test_redaction_catches_spoken_and_spaced_forms_and_keeps_bank_references`, one assertion per form:
    - "+91 98765-00002" becomes MOBILE;
    - "nine eight seven six five zero zero zero zero two" becomes DIGITS;
    - "1234 5678 9012" becomes AADHAAR;
    - "ABCDE1234F" becomes PAN;
    - "4111 1111 1111 1111" becomes CARD;
    - "SR-40102", "TXN-88213", "₹12,450", "due on 2026-11-05" and "••• ••• 4012" stay unchanged.
  - `test_vault_is_a_separate_encrypted_file`: the vault file contains no "9876500002" bytes; the calls DB file contains no ciphertext table.
  - `test_admin_can_reveal_and_it_is_audited`: admin GET gives `{"[MOBILE#1]": {"kind": "MOBILE", "value": "9876500002"}, ...}`; the audit log has `PII_REVEALED` by `admin`; reviewer and analyst get 403.
  - `test_patch_meta_and_feedback_corrections_are_redacted`: a meta patch and a reviewer correction that contain a mobile number are both stored as tokens.
  - `test_no_vault_key_still_redacts`: with `PII_VAULT_KEY` unset the transcript is redacted and the reveal route returns tokens with `value: null`.
- [ ] **Step 2:** Run `cd backend/api && .venv/bin/pip install cryptography==43.0.3 && .venv/bin/pytest -q tests/test_pii.py`; expect FAIL.
- [ ] **Step 3:** Implement `pii.py`, `pii_vault.py` and the route; call `Redactor.redact` in `add_turn` (text and meta), `patch_meta` (patch) and the feedback correction before anything is written. Document key generation in `.env.example`: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- [ ] **Step 4:** Run `tests/test_pii.py tests/test_support.py`; expect PASS. Fix any existing assertion that read a raw mobile or name back from a stored turn, so it expects the token instead.
- [ ] **Step 5:** Add `backend/api/scripts/redact_existing.py`, a one-off that rewrites existing transcripts through the same `Redactor`. Test `test_redact_existing_is_idempotent`: running it twice changes nothing the second time.
- [ ] **Step 6: Commit** `feat(api): redact PII in stored transcripts into a separate encrypted vault, admin reveal with audit`

**Out of scope (later):**
- the caller's recorded audio per turn (`backend/voice` recordings);
- the language model's in-memory context, which needs the real values to verify the caller;
- free-text names spoken in a sentence (only structured name fields are caught);
- Kannada and Hindi number words (Kannada and Devanagari digits are caught after `normalise_refs` turns them into ASCII digits).

### Task P2: Panel: tokens shown as redacted, admin reveal

**Files:**
- Modify: `frontend/src/api/support.ts` (`getCallPii(id): Promise<Record<string, {kind: string; value: string | null}>>`), `src/api/paths/core.ts`, `src/api/mockSupport.ts`, `src/pages/SupportCall.tsx`, `src/components/HighlightedText.tsx` or a new `src/components/PiiText.tsx`
- Test: `src/components/PiiText.test.tsx`, `src/pages/SupportCall.test.tsx`

**Interfaces:**
- Consumes: P1 route and token format.
- Produces:
  - `PiiText({ text, revealed }: { text: string; revealed: Record<string, {kind: string; value: string | null}> | null })` renders each `[KIND#n]` as a grey "Mobile (redacted)" chip, or as the value when `revealed` has it.
  - Call screen: for an admin (`currentUsername()` maps to ADMIN), a "Show personal data" toggle fetches `getCallPii` once and holds it in component state only. Nothing is written to storage, and toggling off drops it.

- [ ] **Step 1: Write the failing tests:**
  - `PiiText` shows "Mobile (redacted)" for `[MOBILE#1]`, and shows the value once `revealed` has it.
  - The call screen shows no toggle for an analyst. For an admin, clicking it calls `getCallPii` once and the transcript shows "9876500002"; toggling off hides it again without another fetch.
- [ ] **Step 2:** Run; expect FAIL.
- [ ] **Step 3:** Implement; use `PiiText` wherever turn text, tool args and corrections render.
- [ ] **Step 4:** Run `npx vitest run src/components/PiiText.test.tsx src/pages/SupportCall.test.tsx && npx tsc --noEmit`; expect PASS.
- [ ] **Step 5: Commit** `feat(panel): redacted personal data chips and admin reveal`

## Order and dependencies

| Task | Needs | Owner |
|---|---|---|
| L0 | none | Anshuman |
| L1 | L0 | Chirag (simulator) |
| L2 | L0 | Chirag (simulator) |
| L3 | L1, L2 | Anshuman |
| L4 | L3 | Anshuman |
| L5 | none | Anshuman |
| L6 | L1, L2, L5 | Anshuman or Pavan |
| T1 | none (Hindi once H1 lands) | Anshuman |
| T2 | T1 | Anshuman |
| P1 | none | Anshuman (core API) |
| P2 | P1 | Anshuman |
| H1 | none | Anshuman |
| H2 | H1 | Pavan (eval) |
| L7 | all | Anshuman |

L5, H1, T1 and P1 can start at once and run in parallel with L1/L2.
