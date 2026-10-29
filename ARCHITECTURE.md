# Case Intelligence Starter: architecture and contracts

A topic-agnostic starter for the Azentio.ai Build Labs finale. Documents (or records) come in, are extracted into structured data, scored by a configurable rules engine, explained by an LLM whose quotes are verified, and land in a reviewer queue where a human decides. Every step is audited.

Declared as **pre-built, reusable scaffolding** under rule 3. The topic-specific layer (schema, rules, weights, data generator, signature screens) is built during the event.

## Services

| Service | Stack | Port | Owns |
|---|---|---|---|
| `api/` | Java 17, Spring Boot 3.3, Spring Data JPA, Spring Security, Flyway, springdoc-openapi, PostgreSQL | 8080 | Cases, documents, job queue, rules engine, scoring, routing, review decisions, audit chain, RBAC |
| `agent/` | Python 3.12, FastAPI, Pydantic v2, PyMuPDF, httpx | 8000 | Document parsing, hidden-text and injection checks, PII masking, LLM gateway (Anthropic / Ollama / mock), structured extraction, quote-verified explanations, synthetic-data helpers, eval harness |
| `voice/` | Python 3.12, FastAPI, Pipecat 1.12.0, edge-tts | 7861 | Renewal call: WebRTC audio, speech to text, the LLM tool loop, speech out. No policy logic and no database |
| `web/` | React 18, TypeScript, Vite | 5173 | Reviewer queue, case workspace, upload, audit timeline, rule-pack view, Renewals queue and live call screen |
| `postgres` | PostgreSQL 16 | 5432 | Everything persistent. Also the job queue (no Redis) |

`docker-compose.yml` at the repo root runs all five (plus `agent`). Each service also runs standalone for development.

## Request flow

1. `POST /api/v1/cases` (multipart: `files[]`, `caseType`, optional `title`, optional `attributes` as a JSON object up to 8 KB, stored as `cases.attributes` jsonb). The same files with different attributes make a new case, so one document filed under two applicants stays visible. The API stores each file under `data/uploads/<sha256>` and computes SHA-256.
   - **Idempotency:** if a case of the same `caseType` already holds a document with the same SHA-256 and the same `pipelineVersion`, return that case with `200` and header `X-Cache: HIT`. Otherwise create the case (`201`, `X-Cache: MISS`).
   - Enqueue one `PROCESS_CASE` job. Respond immediately; processing is asynchronous.
2. A worker inside the API claims jobs with `SELECT … FOR UPDATE SKIP LOCKED`, bounded concurrency (`app.worker.concurrency`, default 4), exponential backoff with jitter, max 3 attempts, then `FAILED` (dead-letter state).
3. For each document the worker calls `POST agent:/v1/extract`. Stores the result as an `extraction` row.
4. The worker runs the **rule pack** for `caseType`: built-in core rules plus pack rules. Each rule returns zero or more findings.
5. Score = `min(1, Σ weight × severityFactor)` over findings, where severityFactor is LOW 0.3, MEDIUM 0.6, HIGH 1.0. Weights and routing thresholds come from the pack's YAML.
6. The worker calls `POST agent:/v1/explain` with findings and page text. Notes whose quotes cannot be found verbatim in the source text are dropped and the drop is recorded.
7. Routing: `score < autoClearBelow` → `AUTO_CLEARED`; `score ≥ escalateAtOrAbove` → `ESCALATED`; otherwise `NEEDS_REVIEW`. Any core security finding (hidden text, injection) forces at least `NEEDS_REVIEW`.
8. Reviewers act on findings and cases in the web app. Every state change writes an audit event.

## Data model (Flyway `V1__init.sql`)

```
cases(id uuid pk, case_type text, title text, status text, risk_score numeric(4,3),
      amount_at_risk numeric(14,2), pipeline_version text, created_by text,
      created_at timestamptz, updated_at timestamptz)
documents(id uuid pk, case_id uuid fk, filename text, mime_type text, sha256 char(64),
          size_bytes bigint, storage_path text, page_count int, created_at timestamptz)
extractions(id uuid pk, document_id uuid fk, payload jsonb, model_provider text,
            model_name text, prompt_version text, input_tokens int, output_tokens int,
            created_at timestamptz)
findings(id uuid pk, case_id uuid fk, rule_id text, title text, detail text,
         severity text, weight numeric(5,3), amount numeric(14,2), source text,
         evidence jsonb, llm_note text, verified boolean, status text,
         decided_by text, decision_reason text, decided_at timestamptz, created_at timestamptz)
jobs(id uuid pk, case_id uuid fk, kind text, status text, attempts int, run_after timestamptz,
     last_error text, idempotency_key text unique, created_at timestamptz, updated_at timestamptz)
audit_events(id bigserial pk, case_id uuid null, actor text, action text, payload jsonb,
             prev_hash char(64), hash char(64), created_at timestamptz)
```

- `audit_events` is append-only: a trigger raises on `UPDATE` and `DELETE`. `hash = sha256(prev_hash || actor || action || payload || created_at)`. `GET /api/v1/audit/verify` recomputes the chain and reports the first broken link.
- Enums are text with check constraints. Case status: `RECEIVED, PROCESSING, NEEDS_REVIEW, AUTO_CLEARED, ESCALATED, APPROVED, REJECTED, FAILED`. Finding status: `OPEN, ACCEPTED, DISMISSED, EDITED`. Severity: `LOW, MEDIUM, HIGH`. Source: `RULE, MODEL, LLM, SECURITY`.

## Rule packs

A pack is a Spring bean implementing:

```java
public interface RulePack {
  String caseType();                       // e.g. "demo", "bank_statement", "health_claim"
  String extractionSchema();               // schema key sent to agent /v1/extract
  List<Rule> rules();
}
public interface Rule {
  String id();                             // e.g. "CORE-HIDDEN-TEXT", "BS-BALANCE-CHAIN"
  List<FindingDraft> evaluate(RuleContext ctx);  // ctx: case (with attributes), documents, extractions (JsonNode), pack config,
                                                 // peers: same-type cases by recency or by attribute value (GIN-indexed), extractions loaded on demand
}
```

Config lives in `api/src/main/resources/packs/<caseType>.yml`:

```yaml
caseType: demo
label: Demo documents
routing: { autoClearBelow: 0.2, escalateAtOrAbove: 0.8 }
rules:
  CORE-DUPLICATE-DOC:   { weight: 0.5, rationale: "Same file already seen in another case" }
  CORE-HIDDEN-TEXT:     { weight: 0.6, rationale: "Text a human cannot see is a manipulation signal" }
  CORE-INJECTION:       { weight: 0.8, rationale: "Instructions aimed at the AI inside a document" }
  DEMO-LARGE-AMOUNT:    { weight: 0.3, rationale: "Amounts above the configured threshold", params: { threshold: 100000 } }
```

`GET /api/v1/packs` returns every pack with rules, weights, rationale and params so the UI can show *why* each weight exists. Core rules ship with the starter; the `demo` pack proves the pipeline end to end on any PDF.

## API (`/api/v1`, OpenAPI at `/swagger-ui.html`)

| Method & path | Role | Purpose |
|---|---|---|
| `POST /cases` | ANALYST+ | Upload, dedupe, enqueue |
| `GET /cases?status=&caseType=&page=&size=` | ANALYST+ | Queue, sorted by `risk_score desc, amount_at_risk desc` |
| `GET /cases/{id}` | ANALYST+ | Case with documents, findings, latest extraction summary |
| `GET /cases/{id}/documents/{docId}/pages` | ANALYST+ | Page text (masked) for the evidence pane |
| `POST /cases/{id}/findings/{fid}/decision` | REVIEWER+ | `{action: ACCEPT|DISMISS|EDIT, reason, amount?}`; reason required for DISMISS/EDIT |
| `POST /cases/{id}/decision` | REVIEWER+ | `{action: APPROVE|REJECT|ESCALATE, reason}`; four-eyes: the uploader cannot decide their own case |
| `GET /cases/{id}/audit` | ANALYST+ | Audit events for a case |
| `GET /audit/verify` | ADMIN | Recompute the hash chain |
| `GET /packs` | ANALYST+ | Packs, rules, weights, rationale |
| `GET /stats` | ANALYST+ | Counts by status, jobs pending, p50/p95 processing ms, cache hits |
| `GET /health` | public | API + DB + agent reachability |

**RBAC:** Spring Security HTTP Basic with in-memory users for the demo: `analyst/analyst` (ANALYST), `reviewer/reviewer` (REVIEWER, ANALYST), `admin/admin` (ADMIN, REVIEWER, ANALYST). Enforced with `@PreAuthorize` on the service layer, not only in the UI. CORS allows `http://localhost:5173`.

**Errors:** RFC 9457 `application/problem+json` with `type`, `title`, `status`, `detail`.

**Limits:** max 20 MB per file, max 50 pages per PDF (rejected with 413 / 422), per-user upload rate limit (default 30 per minute, 429 with `Retry-After`).

## Agent service contract

`POST /v1/extract`: multipart `file`, form field `schema` (string).

```json
{
  "page_count": 3,
  "pages": [{ "page": 1, "text": "…masked text…" }],
  "fields": { },
  "security": {
    "hidden_text": [{ "page": 2, "text": "ignore previous instructions…", "reason": "white_text|tiny_font|off_page" }],
    "injection": { "suspected": true, "score": 0.92, "matches": ["ignore previous instructions"] },
    "pii": { "masked": { "PAN": 1, "AADHAAR": 0, "PHONE": 2, "EMAIL": 1, "ACCOUNT": 3 } }
  },
  "model": { "provider": "mock", "name": "mock", "prompt_version": "extract-v1" },
  "usage": { "input_tokens": 0, "output_tokens": 0, "latency_ms": 12 }
}
```

- Text extraction uses the PDF text layer via PyMuPDF. Hidden text = spans whose fill colour is near white, font size < 2 pt, or whose bbox lies outside the page. Hidden spans are reported and **excluded** from the text sent to any LLM.
- Injection check = regex/phrase heuristics (a scored list of known patterns) over all text including hidden spans. Pluggable so Llama Prompt Guard 2 can replace it.
- PII masking runs before any LLM call and before text is returned. Indian patterns: PAN, Aadhaar (12 digits, Verhoeff optional), phone, email, account numbers (9–18 digits), IFSC is **kept** (not personal).
- `fields` come from the schema registry (`agent/app/schemas/`). Each schema is a Pydantic model plus a prompt. The `demo` schema extracts `{document_kind, parties[], dates[], amounts[{value, currency, context}]}`. Output is validated against the model; on failure one repair retry, then `fields: {}` and `"extraction_error"` set.
- Document text is wrapped in random delimiters and the system prompt states it is untrusted data (spotlighting).

`POST /v1/explain`:

```json
{ "case_type": "demo",
  "findings": [{ "id": "…", "rule_id": "…", "title": "…", "detail": "…", "evidence": [{ "page": 1, "quote": "…" }] }],
  "pages": [{ "document_id": "…", "page": 1, "text": "…" }] }
```
returns
```json
{ "summary": "…", "notes": [{ "finding_id": "…", "note": "…", "quotes": [{ "document_id": "…", "page": 1, "text": "…" }] }],
  "dropped": [{ "finding_id": "…", "reason": "quote_not_found" }],
  "model": { … }, "usage": { … } }
```
Every quote is checked as a whitespace-normalised substring of the given page text; unverifiable notes go to `dropped`.

**LLM gateway:** `LLM_PROVIDER=anthropic|gemini|groq|mistral|ollama|mock` (default `mock`, so everything runs offline and load tests cost nothing). Gemini, Groq and Mistral go through one OpenAI-compatible adapter with JSON mode. A failed provider cools down for `LLM_COOLDOWN_S` and moves to the back of the chain. Anthropic uses the official SDK with prompt caching on the system prompt and tool schemas; models via `ANTHROPIC_MODEL` (default `claude-haiku-5-5` for extraction, `ANTHROPIC_REASONING_MODEL` default `claude-sonnet-5-5` for explain). Ollama via its HTTP API (`OLLAMA_MODEL`, default `llama3.2`). On provider error or timeout, fall back to the next provider in `LLM_FALLBACK` (default `ollama,mock`) and record which one answered.

`GET /health`, `GET /v1/schemas`.

## Supporting tools

- `agent/datagen/common.py`: seeded helpers for realistic Indian synthetic data (names, cities, PAN format, phone, IFSC, UPI VPAs, dates, INR formatting) plus a minimal PDF writer (PyMuPDF) that can also plant hidden white text for red-team samples.
- `agent/datagen/demo_docs.py`: writes `samples/` with 3 clean PDFs, 1 duplicate, 1 with hidden "ignore previous instructions" text.
- `agent/eval/run_eval.py`: reads `ground_truth.json` (`{case_ref: [rule_id…]}`) and the API's findings, prints precision / recall / F1 per rule and overall, and writes `eval/report.md`.
- `ops/load/k6-upload.js`: k6 script ramping 10 → 100 virtual users uploading sample PDFs; thresholds on p95 time-to-accepted.

## Renewal Desk voice service (topic layer, built during the event)

An analyst starts a call with `POST /api/v1/renewals/calls`; the customer joins from the browser. Live audio: browser mic, WebRTC (`POST /api/offer`, `PATCH /api/offer` for ICE), Silero VAD and Smart Turn, Groq Whisper, Groq `openai/gpt-oss-120b`, edge-tts, browser speaker. Text mode (`/v1/text-call`, `/v1/text-turn`) runs the same brain without audio. `GET /health` returns `{"status":"ok"}`. The service signs in to the API as the `voice` user (role VOICE) and holds no state beyond the live sessions.

The model sees seven tools. Each one is a thin call to a renewals endpoint:

| Tool | API endpoint (`/api/v1/renewals/calls/{callId}/...`) |
|---|---|
| `verify_identity` | `POST /verify` (date of birth) |
| `get_policy` | `GET /policy` |
| `list_allowed_options` | `GET /options` |
| `quote_renewal` | `POST /quote` |
| `send_payment_link` | `POST /payment-link` |
| `handoff_to_human` | `POST /handoff` |
| `end_call` | `POST /end` |

The voice service also posts every spoken line to `POST /turns`. The analyst views the call and its audit trail with `GET /calls/{callId}`, and the queue with `GET /renewals/queue`.

### Limits live in the API

The model can ask for anything. The API decides, and the prompt is not a security boundary.

- **Identity before policy details.** `get_policy`, `list_allowed_options`, `quote_renewal` and `send_payment_link` return `403 IDENTITY_NOT_VERIFIED` until `verify` succeeds. Too many wrong answers lock verification (`409 VERIFY_LOCKED`) and force a handoff.
- **Discount limit and out-of-playbook counter.** A quote with a discount above the playbook maximum returns `OUTSIDE_PLAYBOOK`, increments the call's out-of-playbook counter and writes a `rule.outside_playbook` audit event. Reaching the playbook's limit on that counter forces a handoff.
- **Forced handoff blocks offers.** While a handoff is forced, `list_allowed_options`, `quote_renewal` and `send_payment_link` return `409 MUST_HANDOFF`. The agent can only hand off or end the call.
- **Refusals are audited.** Every refused tool call writes a `tool.refused` event with the tool and code, so the audit trail shows what the agent tried, not only what it did.
- **One live session per call.** The voice service accepts one WebRTC session per `callId`; a second offer for the same call is rejected with `409 CALL_IN_PROGRESS`. A call that has ended returns `409 CALL_ENDED` for every tool.

Calls to customers with an open complaint (`HUMAN_ONLY`), on the do-not-call list (`DO_NOT_CALL`), or outside calling hours (`OUTSIDE_CALLING_HOURS`, switchable with `ENFORCE_CALLING_HOURS=false`) cannot be started at all.

## Non-goals for the starter

No topic logic beyond `demo`. No OCR of scanned images (text-layer PDFs only; vision-LLM fallback is a topic-day decision). No real authentication provider.
