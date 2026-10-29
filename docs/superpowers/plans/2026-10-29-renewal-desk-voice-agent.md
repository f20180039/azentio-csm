# Renewal Desk Voice Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A browser voice agent that calls an insurance customer whose policy is about to lapse, verifies them, explains the renewal premium, offers only what the playbook allows through API-checked tools, hands over to a human when rules say so, and leaves an auditable call record a CSM approves.

**Architecture:** Three services. The Spring API (starter) owns policies, the lapse-risk queue, the playbook and every tool endpoint; each call is a starter *case* (`caseType=renewal_call`) so the audit hash chain and review decision are reused. A new Python voice service runs the Pipecat pipeline (VAD → Groq Whisper → Groq gpt-oss-120b with tools → edge-tts) and a text-mode twin of the same brain; its tools are thin HTTP calls to the API, so limits live in the API, never in the prompt. The React app gains a renewals queue and a call screen.

**Tech Stack:** Java 17 / Spring Boot 3 / Flyway / Postgres (existing); Python 3.12, Pipecat `pipecat-ai[webrtc,groq]==1.12.0`, `edge-tts==7.3.1`, httpx, FastAPI, pytest; React 18 + `@pipecat-ai/client-js` + `@pipecat-ai/small-webrtc-transport`.

**Spec:** design doc and prototype at https://claude.ai/artifact/WQGWMNUigbnZKH5fVEhCH7 ("Renewal Desk"). Latency spike: `../spikes/voice-loop/` (throwaway; port from it, don't import it).

## Global Constraints

- Never call Anthropic. The voice service reads only `GROQ_API_KEY` (and `GEMINI_API_KEY` if a fallback is added) from `../.env` and pops `ANTHROPIC_API_KEY` from its environment.
- Groq models: STT `whisper-large-v3-turbo`; LLM `openai/gpt-oss-120b` with reasoning effort `low`.
- Pin every new dependency to an exact version released at least 2 weeks before 2026-10-29 (Pipecat 1.12.0, released 26 Sep, is the reference).
- Synthetic data only; fictional insurer name **Lotusleaf General Insurance**. No real people, insurers or HealthPlix data.
- Money is INR, integer rupees, stored as `numeric(12,0)`; spoken amounts in words are the LLM's job, the API returns numbers.
- Time zone `Asia/Kolkata`; calling hours 09:00–21:00 inclusive start, enforced by the API (`app.renewals.enforce-calling-hours`, default `true`).
- Agent opening line (exact, playbook field `greeting`): "Hello, this call is recorded. I'm the renewals assistant from Lotusleaf General Insurance. Am I speaking with {holderName}?"
- Discount limit in the demo playbook: `0` percent.
- Every tool endpoint writes one audit event via `AuditService.record(caseId, actor, action, payload)`.
- New pre-built/reused code is declared in `README.md` "Declaration of reused components"; Pipecat (BSD-2-Clause) and edge-tts are listed under third-party libraries.
- Repo is not under git yet: each task's "Commit" step runs only once the user has approved `git init`; otherwise skip it.

## Review Focus

1. **Policy details requested before identity is verified** → API answers `403 IDENTITY_NOT_VERIFIED`, the agent asks for date of birth again. Test in Task 3 (`policyBeforeVerifyIsRefused`).
2. **Three wrong dates of birth** → third failure returns `mustHandoff=true`; further verify attempts return `409`. Test in Task 3 (`thirdFailedVerifyForcesHandoff`).
3. **Discount asked twice** → each `quote` with `discountPercent > limit` returns `422 OUTSIDE_PLAYBOOK`; the second sets `mustHandoff=true`. Test in Task 3 (`secondOutOfPlaybookRequestForcesHandoff`).
4. **Caller interrupts on the very first turn / silence** → no LLM call on an empty transcript; text mode rejects blank text with 400. Tests in Task 5 (`blankTextTurnIsRejected`) and Task 6 (`empty_user_turn=None` asserted in `test_pipeline_params`).
5. **Start a call for a human-only, do-not-call, or out-of-hours policy** → `409` with the reason; the web button is disabled for non-`AGENT_CALL` routes. Tests in Task 2 (`humanOnlyPolicyCannotBeCalled`, `outsideCallingHoursIsRefused`).

---

## File Structure

```
starter/
  api/src/main/resources/db/migration/V3__renewals.sql        policies + calls tables
  api/src/main/resources/db/migration/R__renewal_seed.sql      generated synthetic policies (Task 1)
  api/src/main/resources/playbooks/health-renewal.yml          demo playbook
  api/src/main/java/ai/caseintel/api/renewals/
    PolicyEntity.java, PolicyRepository.java                   policies
    CallEntity.java, CallRepository.java                       one row per call (id = case id)
    Playbook.java, PlaybookLoader.java                         typed playbook + YAML loader
    LapseRisk.java                                             signals → score → route (pure)
    RenewalService.java                                        queue, start call, tools, end
    RenewalDtos.java                                           request/response records
    RenewalController.java                                     /api/v1/renewals/**
  api/src/test/java/ai/caseintel/api/renewals/
    LapseRiskTest.java, PlaybookLoaderTest.java, RenewalServiceTest.java
  agent/datagen/renewals.py                                    seeded generator → R__renewal_seed.sql
  voice/                                                       NEW service
    requirements.txt, requirements-dev.txt, Dockerfile, pytest.ini
    app/config.py        env loading (Groq only, Anthropic popped)
    app/api_client.py    typed httpx client for /api/v1/renewals
    app/tools.py         tool schemas + handlers (shared by voice and text)
    app/prompt.py        system prompt from playbook
    app/brain.py         text-mode LLM loop with tools (Groq, OpenAI-compatible)
    app/edge_tts_service.py  Pipecat TTS service wrapping edge-tts (port from spike)
    app/pipeline.py      Pipecat pipeline factory
    app/main.py          FastAPI: POST /api/offer, POST /v1/text-turn, GET /health
    tests/...
  web/src/pages/Renewals.tsx, web/src/pages/Call.tsx, web/src/api/renewals.ts
  docker-compose.yml (voice service), README.md, ARCHITECTURE.md
```

---

### Task 1: Policies, calls and synthetic data

**Files:**
- Create: `api/src/main/resources/db/migration/V3__renewals.sql`
- Create: `agent/datagen/renewals.py`, generated `api/src/main/resources/db/migration/R__renewal_seed.sql`
- Create: `api/src/main/java/ai/caseintel/api/renewals/{PolicyEntity,PolicyRepository,CallEntity,CallRepository}.java`
- Test: `agent/tests/test_renewals_datagen.py`, extend `api/src/test/java/ai/caseintel/api/it/PersistenceIT.java`

**Interfaces:**
- Produces table `policies(id text PK, holder_name text, date_of_birth date, mobile_last4 char(4), product text, sum_insured numeric(12,0), expires_on date, last_premium numeric(12,0), renewal_premium numeric(12,0), premium_breakdown jsonb, addons jsonb, claim_rejected_12m bool, open_complaint bool, autodebit_failed bool, reminders_ignored int, do_not_call bool)`.
  - `premium_breakdown`: `[{"label": "Age band 41–45 to 46–50", "amount": 2610}, ...]`
  - `addons`: `[{"code": "OPD", "name": "Outpatient cover", "premium": 2100, "optional": true}]`
- Produces table `calls(id uuid PK REFERENCES cases(id), policy_id text REFERENCES policies(id), started_at timestamptz, ended_at timestamptz, identity_verified bool default false, verify_failures int default 0, out_of_playbook_requests int default 0, must_handoff bool default false, outcome text, last_quote jsonb, payment_link_sent bool default false, handoff_reason text, callback_at text, transcript jsonb default '[]')`.
- Produces `PolicyRepository extends JpaRepository<PolicyEntity,String>`, `CallRepository extends JpaRepository<CallEntity,UUID>`.
- Produces `python -m datagen.renewals --seed 7 --count 40 --today 2026-10-29 --out ../api/src/main/resources/db/migration/R__renewal_seed.sql`.

- [ ] **Step 1: Write the failing generator test** `test_renewals_datagen.py`:
  - `test_same_seed_same_sql`: two runs with seed 7 produce identical text.
  - `test_demo_policy_present`: output contains `'HF-2291-0457'`, `'Meera Iyer'`, `'1980-03-14'`, renewal premium `18450`, last premium `15120`, OPD add-on premium `2100`, expiry `2026-11-03` (with `--today 2026-10-29`).
  - `test_mix`: of 40 policies at least 3 have `open_complaint`, at least 2 `do_not_call`, at least 8 expire within 7 days, at least 8 have premium up more than 15%; renewal premium equals last premium plus the sum of breakdown amounts for every row.
- [ ] **Step 2: Run** `cd agent && .venv/bin/pytest tests/test_renewals_datagen.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement `agent/datagen/renewals.py`** with `random.Random(seed)`, fictional Indian names, products `Health family floater | Health individual | Motor comprehensive | Motor third-party | Term life`; the five prototype customers (Meera Iyer, Arjun Mehta with open complaint + rejected claim, Sana Qureshi, Kavya Rao with autodebit failed, Rohan Das +9%) are fixed rows; the rest random. Emits `INSERT ... ON CONFLICT (id) DO UPDATE` statements so the repeatable migration reloads cleanly. Write `V3__renewals.sql` with the two tables and `CREATE INDEX calls_policy_idx ON calls(policy_id)`.
- [ ] **Step 4: Run** the generator, then `pytest` → PASS.
- [ ] **Step 5: Entities + IT.** Add `PersistenceIT.renewalSeedLoads()`: after Flyway, `policies` has 40 rows and `HF-2291-0457` maps to `PolicyEntity` with `renewalPremium = 18450` and two breakdown items. Run `./mvnw test -Dintegration` with `IT_DB_URL` pointing at a throwaway local DB (create and drop it) → PASS.
- [ ] **Step 6: Commit** (only once git is approved) `feat(renewals): policies, calls and synthetic seed`.

### Task 2: Playbook, lapse risk and the queue

**Files:**
- Create: `renewals/Playbook.java`, `renewals/PlaybookLoader.java`, `renewals/LapseRisk.java`, `renewals/RenewalDtos.java`, `resources/playbooks/health-renewal.yml`
- Create: `renewals/RenewalService.java` (queue + startCall only in this task), `renewals/RenewalController.java`
- Modify: `config/SecurityConfig.java` (user `voice`/`voice`, role `VOICE`), `config/AppProperties.java` + `application.yml` (`app.renewals.enforce-calling-hours`, `app.renewals.playbook: playbooks/health-renewal.yml`)
- Test: `LapseRiskTest.java`, `PlaybookLoaderTest.java`, `RenewalServiceTest.java`

**Interfaces:**
- `record Playbook(String id, int version, String greeting, int maxDiscountPercent, List<String> paymentPlans, boolean removableOptionalAddons, int maxOutOfPlaybookRequests, int maxVerifyFailures)`; demo values `health-renewal`, `3`, the exact greeting, `0`, `[annual, quarterly]`, `true`, `2`, `3`.
- `PlaybookLoader.load(String classpathPath): Playbook` throws `InvalidPackException` on missing fields or negative limits.
- `enum Route { AGENT_CALL, HUMAN_ONLY, REMINDER_SMS }`
- `record Signal(String code, String label, Severity severity, double weight)`; `record Risk(BigDecimal score, List<Signal> signals, Route route)`
- `LapseRisk.assess(PolicyEntity p, LocalDate today): Risk` — score via existing `Scoring.score(List<Weighted>)` with `FindingSource.RULE`. Signal table (code, severity, weight):

  | Code | When | Severity | Weight |
  |---|---|---|---|
  | `EXPIRY_7D` | expires in 0–7 days | HIGH | 0.40 |
  | `EXPIRY_14D` | expires in 8–14 days | MEDIUM | 0.40 |
  | `PREMIUM_UP_15` | renewal ≥ 1.15 × last | MEDIUM | 0.50 |
  | `PREMIUM_UP_5` | 1.05 ≤ ratio < 1.15 | LOW | 0.50 |
  | `CLAIM_REJECTED` | `claim_rejected_12m` | HIGH | 0.30 |
  | `AUTODEBIT_FAILED` | `autodebit_failed` | MEDIUM | 0.40 |
  | `REMINDERS_IGNORED` | `reminders_ignored ≥ 2` | LOW | 0.50 |

  Route: `open_complaint || do_not_call` → `HUMAN_ONLY`; else score `< 0.35` → `REMINDER_SMS`; else `AGENT_CALL`. Expired policies (negative days) are excluded from the queue.
- `GET /api/v1/renewals/queue` (role `ANALYST`) → `List<QueueItem(String policyId, String holderName, String product, LocalDate expiresOn, int daysToExpiry, BigDecimal score, List<Signal> signals, Route route)>` sorted by score desc, then days asc.
- `POST /api/v1/renewals/calls` body `{policyId}` (role `ANALYST`) → `201 {callId, caseId, greeting}`; creates a case `caseType="renewal_call"`, title `"Renewal call · {holderName}"`, attributes `{"policyId": ...}`, status `PROCESSING`, plus a `calls` row; audit `call.started`. Refuses with `409` and `detail` = `HUMAN_ONLY`, `DO_NOT_CALL` or `OUTSIDE_CALLING_HOURS`.
- `RenewalService` takes a `java.time.Clock` bean (add `Clock.system(ZoneId.of("Asia/Kolkata"))` in config) so tests fix the time.

- [ ] **Step 1: Failing tests.**
  - `LapseRiskTest.meeraScoresAndRoutesToAgent`: Meera's row on 2026-10-29 → signals `[EXPIRY_7D, PREMIUM_UP_15, REMINDERS_IGNORED]`, score `0.850`, route `AGENT_CALL`.
  - `LapseRiskTest.openComplaintIsHumanOnly`, `lowScoreGetsReminderSms` (Rohan, +9%, 21 days → `0.150`, `REMINDER_SMS`), `scoreCapsAtOne`.
  - `PlaybookLoaderTest.loadsDemoPlaybook` (all values above, greeting exact), `rejectsNegativeDiscount`.
  - `RenewalServiceTest.queueIsSortedAndExcludesExpired`, `humanOnlyPolicyCannotBeCalled`, `outsideCallingHoursIsRefused` (clock 21:30 IST → 409 `OUTSIDE_CALLING_HOURS`; with `enforce-calling-hours=false` → 201), `startCallCreatesCaseCallRowAndAudit`.
- [ ] **Step 2: Run** `./mvnw test -Dtest='LapseRiskTest,PlaybookLoaderTest,RenewalServiceTest'` → FAIL.
- [ ] **Step 3: Implement** the files above; `RenewalServiceTest` uses the same in-memory/mocking style as `CaseDecisionTest`.
- [ ] **Step 4: Run** the three tests, then the full `./mvnw test` → PASS.
- [ ] **Step 5: Commit** `feat(renewals): playbook, lapse risk queue, start call`.

### Task 3: Tool endpoints with limits enforced in the API

**Files:**
- Modify: `renewals/RenewalService.java`, `renewals/RenewalController.java`, `renewals/RenewalDtos.java`
- Test: `RenewalServiceTest.java`

**Interfaces** (all under `/api/v1/renewals/calls/{callId}`, role `VOICE` or `ANALYST`; every response includes `mustHandoff: boolean`; every call writes an audit event named in brackets):
- `POST /verify` `{dateOfBirth: "YYYY-MM-DD"}` → `{verified, attemptsLeft, mustHandoff}` [`identity.verified` | `identity.failed`]. Third failure sets `must_handoff`; any verify after that → `409 VERIFY_LOCKED`.
- `GET /policy` → `403 IDENTITY_NOT_VERIFIED` until verified; then `{policyId, product, sumInsured, expiresOn, lastPremium, renewalPremium, breakdown[], addons[], mobileLast4, mustHandoff}` [`tool.get_policy`].
- `GET /options` → `{paymentPlans, removableAddons: [{code,name,saving}], maxDiscountPercent, mustHandoff}` [`tool.list_allowed_options`]; also gated on verification.
- `POST /quote` `{dropAddons: [code], paymentPlan: "annual"|"quarterly", discountPercent: int = 0}` → `200 {quoteId, annualPremium, instalments, perInstalment, mustHandoff}` [`tool.quote_renewal`]. `perInstalment` = ceil(annual / instalments). Unknown or non-optional add-on, unknown plan → `422 INVALID_OPTION`. `discountPercent > maxDiscountPercent` → `422 OUTSIDE_PLAYBOOK`, increments `out_of_playbook_requests`, and sets `must_handoff` when it reaches `maxOutOfPlaybookRequests` [`rule.outside_playbook`]. Saves `last_quote`.
- `POST /payment-link` `{quoteId}` → `{sent: true, channel: "SMS", mobileLast4}` (mock) [`tool.send_payment_link`]; `409` if `quoteId` ≠ last quote.
- `POST /handoff` `{reason, callbackAt?}` → `{queued: true}`; sets case status `ESCALATED` [`tool.handoff_to_human`].
- `POST /turns` `{role: "agent"|"customer", text, at}` → `204`; appends to `transcript` (no audit event per turn).
- `POST /end` → `{outcome}` where outcome = `HANDED_OFF` if handoff queued, else `RENEWAL_PENDING_PAYMENT` if a payment link was sent, else `NO_DECISION`; sets `ended_at`, case status `NEEDS_REVIEW` unless `ESCALATED` [`call.ended`]. Idempotent.
- `GET /` (role `ANALYST`) → `CallView {callId, caseId, policyId, holderName, identityVerified, verifyFailures, outOfPlaybookRequests, mustHandoff, outcome, lastQuote, paymentLinkSent, handoffReason, callbackAt, transcript, summary[]}` where `summary` is `[{statement, quote}]` built deterministically: one item per audit event of type `tool.quote_renewal`, `tool.send_payment_link`, `rule.outside_playbook`, `tool.handoff_to_human`, with `quote` = the last customer turn before that event. Statements are fixed strings, e.g. "Customer asked for a discount beyond the playbook limit."
- Ending or any tool on an ended call → `409 CALL_ENDED`.

- [ ] **Step 1: Failing tests** in `RenewalServiceTest`: `policyBeforeVerifyIsRefused`, `wrongDobCountsDown` (attemptsLeft 2 then 1), `thirdFailedVerifyForcesHandoff`, `quoteDropsOpdQuarterly` (Meera: drop `OPD`, quarterly → annual `16350`, perInstalment `4088`), `nonOptionalAddonIsInvalid`, `secondOutOfPlaybookRequestForcesHandoff`, `paymentLinkNeedsLatestQuote`, `endOutcomes` (three cases), `toolsAfterEndAreRefused`, `summaryQuotesPrecedingCustomerTurn`.
- [ ] **Step 2: Run** `./mvnw test -Dtest=RenewalServiceTest` → FAIL.
- [ ] **Step 3: Implement.** Map refusals through the existing `ApiException` + `ApiExceptionHandler` so bodies are problem+json with `detail` = the code (`IDENTITY_NOT_VERIFIED`, `OUTSIDE_PLAYBOOK`, ...).
- [ ] **Step 4: Run** full `./mvnw test` → PASS. Then one manual curl pass against a running API (temp DB) for start → verify → policy → quote → payment-link → end, and `GET /api/v1/cases/{caseId}/audit` shows the chain.
- [ ] **Step 5: Commit** `feat(renewals): checked tool endpoints and call record`.

### Task 4: Voice service skeleton, API client and tools

**Files:**
- Create: `voice/requirements.txt` (`pipecat-ai[webrtc,groq]==1.12.0`, `edge-tts==7.3.1`, `httpx==0.28.1`, `fastapi==0.115.6`, `uvicorn[standard]==0.32.1`, `python-dotenv` pinned), `voice/requirements-dev.txt` (`pytest==8.3.4`), `voice/pytest.ini`
- Create: `voice/app/config.py`, `voice/app/api_client.py`, `voice/app/tools.py`, `voice/app/prompt.py`
- Test: `voice/tests/test_tools.py`, `voice/tests/test_prompt.py`, `voice/tests/test_config.py`

**Interfaces:**
- `config.Settings` (frozen dataclass): `groq_api_key`, `stt_model="whisper-large-v3-turbo"`, `llm_model="openai/gpt-oss-120b"`, `api_base="http://localhost:8080/api/v1"`, `api_user="voice"`, `api_password="voice"`, `tts_voice="en-IN-NeerjaNeural"`. `load_settings(env_file: Path | None) -> Settings` reads only the keys it needs and always does `os.environ.pop("ANTHROPIC_API_KEY", None)`.
- `api_client.RenewalsApi(settings, transport: httpx.AsyncBaseTransport | None = None)` with async methods mirroring Task 3: `verify(call_id, dob)`, `policy(call_id)`, `options(call_id)`, `quote(call_id, drop_addons, payment_plan, discount_percent)`, `payment_link(call_id, quote_id)`, `handoff(call_id, reason, callback_at)`, `turn(call_id, role, text)`, `end(call_id)`, `call(call_id)`. Each returns the decoded JSON dict; a 4xx problem response is returned as `{"error": <detail>, "status": <code>, "mustHandoff": ...}` instead of raising, so the LLM sees the refusal. 5xx and network errors raise `ApiUnavailable`.
- `tools.TOOL_SCHEMAS: list[dict]` (OpenAI function format) for `verify_identity(date_of_birth)`, `get_policy()`, `list_allowed_options()`, `quote_renewal(drop_addons, payment_plan, discount_percent)`, `send_payment_link(quote_id)`, `handoff_to_human(reason, callback_time?)`, `end_call()`.
- `tools.run_tool(api: RenewalsApi, call_id: str, name: str, args: dict) -> dict` dispatches; unknown name → `{"error": "UNKNOWN_TOOL"}`.
- `prompt.system_prompt(playbook: dict, holder_name: str) -> str`. Must contain: the exact greeting with the name filled in; "Never state any policy detail until verify_identity returns verified"; "Only offer what list_allowed_options returns; if a tool returns an error, say so plainly and do not promise anything"; "If any tool returns mustHandoff true, or the customer asks for a person, mentions a death, illness in distress or a complaint, call handoff_to_human"; "Reply in one or two short spoken sentences, no lists, no markdown, say amounts in words".

- [ ] **Step 1: Failing tests.**
  - `test_config.test_anthropic_key_never_loaded` (env file with `ANTHROPIC_API_KEY=x` and `GROQ_API_KEY=g` → settings has groq key, `os.environ` lacks the Anthropic key).
  - `test_tools.test_refusal_is_returned_not_raised` (MockTransport 403 problem `IDENTITY_NOT_VERIFIED` → `{"error": "IDENTITY_NOT_VERIFIED", "status": 403, ...}`), `test_quote_maps_arguments` (asserts request JSON `{"dropAddons":["OPD"],"paymentPlan":"quarterly","discountPercent":0}`), `test_unknown_tool`, `test_server_error_raises`.
  - `test_prompt.test_greeting_and_rules_present`.
- [ ] **Step 2: Run** `cd voice && python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt -r requirements.txt && .venv/bin/pytest -q` → FAIL.
- [ ] **Step 3: Implement.** Basic auth on every request; 5 s timeout.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(voice): API client, tools and prompt`.

### Task 5: Text-mode brain

**Files:**
- Create: `voice/app/brain.py`; add `POST /v1/text-turn` and `POST /v1/text-call` to `voice/app/main.py`
- Test: `voice/tests/test_brain.py`, `voice/tests/test_main.py`

**Interfaces:**
- `class CallBrain(llm: ChatClient, api: RenewalsApi, call_id: str, system: str)`; `async reply(user_text: str) -> BrainTurn(text: str, tool_calls: list[ToolTrace])`. Loop: append user turn → chat completion with `TOOL_SCHEMAS` → run each tool via `run_tool` → feed results back → until a plain text answer or 5 tool rounds (then reply "Let me get a colleague to help you." and call `handoff_to_human` with reason `TOOL_LOOP_LIMIT`). Posts customer and agent turns to `/turns`.
- `ChatClient` protocol: `async complete(messages, tools) -> dict` (OpenAI response message). `GroqChatClient` uses httpx against `https://api.groq.com/openai/v1/chat/completions` with `reasoning_effort: "low"`.
- Brains live in an in-process dict keyed by `call_id`.
- `POST /v1/text-call` `{callId, holderName}` → `{greeting}` (creates the brain; greeting is spoken by the agent first and posted as an agent turn).
- `POST /v1/text-turn` `{callId, text}` → `{reply, toolCalls}`; blank `text` → `400`; unknown `callId` → `404`.

- [ ] **Step 1: Failing tests** with a scripted `ChatClient` (queue of responses, like the starter's `Scripted`) and a MockTransport API:
  - `test_tool_round_then_text`: model asks `verify_identity`, then answers → `reply` is the text, `tool_calls[0].name == "verify_identity"`, the API saw `POST .../verify`.
  - `test_refusal_reaches_model`: API returns 422 `OUTSIDE_PLAYBOOK`; the second model call's messages include a tool message containing `OUTSIDE_PLAYBOOK`.
  - `test_tool_loop_limit_hands_off`.
  - `test_main.blankTextTurnIsRejected`, `unknownCallIs404`.
- [ ] **Step 2: Run** `.venv/bin/pytest -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS. Then one live text call with the real Groq key against a running API: verify Meera, ask for a discount twice, confirm `GET /renewals/calls/{id}` shows `mustHandoff` and a handoff. No Anthropic in the process.
- [ ] **Step 5: Commit** `feat(voice): text-mode call brain`.

### Task 6: Live voice pipeline

**Files:**
- Create: `voice/app/edge_tts_service.py` (port `EdgeTTSService` from `../spikes/voice-loop/bot.py`), `voice/app/pipeline.py`; add `POST /api/offer` to `voice/app/main.py`
- Test: `voice/tests/test_pipeline.py`

**Interfaces:**
- `build_pipeline(settings, call_id: str, holder_name: str, transport) -> PipelineTask`: Silero VAD, `GroqSTTService(model=stt_model)`, `GroqLLMService(model=llm_model)` with `TOOL_SCHEMAS` registered and each handler wired to `run_tool`, context aggregator with `empty_user_turn=None`, `EdgeTTSService(voice)`, transport out. The greeting is queued as the first assistant message so the agent speaks first. An observer posts final customer transcriptions and agent sentences to `/turns`. On client disconnect → `api.end(call_id)`.
- `POST /api/offer` `{sdp, type, pc_id?, requestData: {callId, holderName}}` → SDP answer, using Pipecat's `SmallWebRTCConnection` the same way the spike's runner does; one pipeline per connection.
- Smart-turn: start with Pipecat's default end-of-turn settings and `stop_secs=0.8` on VAD; record the measured p50 in the README.

- [ ] **Step 1: Failing test** `test_pipeline.test_pipeline_params`: with a fake transport, `build_pipeline` returns a task whose user aggregator has `empty_user_turn is None`, whose LLM has exactly the 7 tool names registered, and whose first context message is the greeting for "Meera Iyer".
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS. Then adapt `../spikes/voice-loop/client_test.py` into `voice/scripts/headless_call.py` (synthesised customer audio for: "yes speaking", "fourteenth March nineteen eighty", "can you give me a discount") against a live API; it prints per-turn latency and the API call record must show `identity.verified` and `tool.list_allowed_options`. Paste the latency table into the README.
- [ ] **Step 5: Commit** `feat(voice): live Pipecat pipeline with checked tools`.

### Task 7: Web: renewals queue and call screen

**Files:**
- Create: `web/src/api/renewals.ts` (+ `renewals.test.ts`), `web/src/pages/Renewals.tsx`, `web/src/pages/Call.tsx` (+ `Call.test.tsx`)
- Modify: `web/src/App.tsx` (routes `/renewals`, `/renewals/calls/:callId`; nav link "Renewals"), `web/src/api/types.ts`, `web/package.json` (add `@pipecat-ai/client-js`, `@pipecat-ai/small-webrtc-transport`, exact versions ≥ 2 weeks old and compatible with the 1.12.0 server), `web/.env.example` (`VITE_VOICE_BASE=http://localhost:7861`)

**Interfaces:**
- `renewals.ts`: `getQueue(): Promise<QueueItem[]>`, `startCall(policyId): Promise<{callId, caseId, greeting}>`, `getCall(callId): Promise<CallView>`, `endCall(callId)`, `textTurn(callId, text)` (voice service), types mirroring Task 2/3 DTOs.
- Queue page: table like prototype screen 1 (holder, product, expiry, score bar, signal pills by severity, route); "Start agent call" enabled only for `AGENT_CALL`; others show "Agent may not call" or "Reminder SMS".
- Call page: Connect/Hang up via Pipecat client to `${VITE_VOICE_BASE}/api/offer` with `requestData {callId, holderName}`; live transcript from the client's transcript events; guardrail panel (recording disclosed, identity verified, offers within playbook, handoff) and call facts driven by polling `getCall` every 1 s; "Type instead" input that uses `textTurn`; after end, outcome pill, summary with quotes, audit chain from the existing `/cases/{caseId}/audit`, and the existing approve decision.
- Mock mode (`VITE_MOCK=1`) returns the prototype's sample queue and a scripted call so the UI works without servers.

- [ ] **Step 1: Failing tests:** `renewals.test.ts` (`startCall` posts `{policyId}` with basic auth; a 409 problem surfaces its `detail`), `Call.test.tsx` (mock mode: after scripted turns the identity dot turns ok and the outcome pill reads "Renewed with changes · payment pending").
- [ ] **Step 2: Run** `npm test` → FAIL.
- [ ] **Step 3: Implement**, reusing `StatusPill`, `Toasts` and `global.css` tokens.
- [ ] **Step 4: Run** `npm test`, `npx tsc --noEmit`, `npm run build` → PASS. Manual: full call in Chrome with a headset against running API + voice service.
- [ ] **Step 5: Commit** `feat(web): renewals queue and live call screen`.

### Task 8: One command, docs and declarations

**Files:**
- Create: `voice/Dockerfile` (python:3.12-slim, no MLX/local Whisper)
- Modify: `docker-compose.yml` (service `voice`, port 7861, `env_file: .env`, `API_BASE=http://api:8080/api/v1`, depends on `api`; web gets `VITE_VOICE_BASE`), `README.md` (run steps, latency table, models: Groq Whisper + gpt-oss-120b + edge-tts; reuse declaration rows for `voice/app/edge_tts_service.py` ported from the event-day spike and Pipecat/edge-tts licences), `ARCHITECTURE.md` (voice service, tool endpoints, "limits live in the API" section), `.env.example` (`VOICE_API_USER`, `VOICE_API_PASSWORD`)

- [ ] **Step 1:** `docker compose up --build` from clean; `curl localhost:7861/health` → `{"status":"ok"}`; queue loads in the browser at the web port.
- [ ] **Step 2:** Run all suites: `api ./mvnw test`, `agent .venv/bin/pytest -q`, `voice .venv/bin/pytest -q`, `web npm test` → all PASS.
- [ ] **Step 3:** Record a 3-minute backup demo video of the happy path and the discount-pushback path.
- [ ] **Step 4: Commit** `chore: compose, docs, declarations for Renewal Desk`.

---

**Next plans (not in this one):** simulated-customer evaluation (`voice/eval/simulate.py`, the metrics table in the design doc); #09 studio (playbook editor + pre-launch tests).
