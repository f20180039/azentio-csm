# Case Intelligence Starter

Reusable scaffolding for document-driven review workflows. Documents come in, structured data comes out, a configurable rules engine scores each case, an LLM explains the findings with quotes it must prove, and a human reviewer decides. Every step lands in a tamper-evident audit log.

Design and contracts: [ARCHITECTURE.md](ARCHITECTURE.md). Per-service details: [api/](api/README.md), [agent/](agent/README.md), [web/](web/README.md).

## Run it

**With Docker**

```bash
docker compose up --build
```

| What | Where |
|---|---|
| Web app | http://localhost:5173 |
| API and Swagger | http://localhost:8080/swagger-ui.html |
| Agent | http://localhost:8000/health |
| Postgres | localhost:5433 (host 5432 is left for a local Postgres) |

Sign in as `analyst/analyst`, `reviewer/reviewer` or `admin/admin`.

**Models:** copy `.env.example` to `.env` and add whichever keys you have. The supported providers are Anthropic, Gemini, Groq, Mistral, local Ollama and a mock.
- `LLM_PROVIDER` is tried first, then `LLM_FALLBACK` in order.
- An error, timeout, rate limit or refusal moves to the next provider. A provider with no key is skipped instantly.
- A provider that just failed sits out for `LLM_COOLDOWN_S` seconds, so later requests don't wait on it.
- Without a `.env` everything runs on the mock, which costs nothing and works offline.
- `.env.example` has ready-made settings for demo day, development and offline use.

**Without Docker**

1. Create a database: `createdb caseintel`, or reuse an existing one by passing `DB_URL`.
2. Start the agent: `cd agent && LLM_PROVIDER=ollama .venv/bin/uvicorn app.main:app --port 8000`
3. Start the API: `cd api && DB_URL=jdbc:postgresql://localhost:5432/caseintel ./mvnw spring-boot:run`
4. Start the web app: `cd web && npm run dev`. Use `npm run dev:mock` for the UI alone, on example data.

## Try it

```bash
cd samples
curl -u analyst:analyst -F caseType=demo -F files=@clean_1.pdf -i http://localhost:8080/api/v1/cases                # 201, X-Cache: MISS
curl -u analyst:analyst -F caseType=demo -F files=@duplicate_of_clean_1.pdf -i http://localhost:8080/api/v1/cases   # 200, X-Cache: HIT
curl -u analyst:analyst -F caseType=demo -F files=@redteam_hidden_text.pdf -i http://localhost:8080/api/v1/cases    # ends ESCALATED
curl -u analyst:analyst -F caseType=demo -F 'attributes={"policyNo":"POL-1"}' -F files=@clean_1.pdf -i http://localhost:8080/api/v1/cases   # 201: same file, new attributes
cd ../agent && .venv/bin/python eval/run_eval.py --truth ../samples/ground_truth.json --api http://localhost:8080 --samples ../samples --case-type demo --user analyst:analyst
```

## Tests

| Service | Command | Coverage |
|---|---|---|
| api | `./mvnw test` (add `-Dintegration` for the Postgres tests) | Scoring and routing, pack loading, core rules, audit hash chain, four-eyes, rate limit, backoff |
| agent | `.venv/bin/pytest -q` | Hidden text, injection scoring, PII masking, quote verification, schema repair, provider fallback, `/v1/extract` |
| web | `npm test` | API error handling, response shapes, finding card, evidence highlight, mock-mode flow |

## Declaration of reused components

Rule 3 of Azentio.ai Build Labs asks for this. Everything in this folder was built before the event as generic scaffolding, with no knowledge of the problem statement.

| Component | What it is | Built |
|---|---|---|
| `api/` | Spring Boot service: cases, upload dedupe, Postgres job queue, rule-pack engine, scoring and routing, review decisions, audit hash chain, RBAC | Before the event |
| `agent/` | FastAPI service: PDF text extraction, hidden-text and injection checks, PII masking, LLM gateway with fallback, quote verification, eval harness | Before the event |
| `web/` | React reviewer app: queue, case workspace, audit view, rule packs | Before the event |
| `agent/app/voice/tts.py` | Text to speech (edge-tts, ElevenLabs), copied and trimmed from the team member's own earlier project solarfile-reels (private repo, access on request; `backend/app/pipeline/tts.py`, commit `f089eaa`, Aug 2026) | Before the event, for a different project |
| `demo` rule pack and `samples/` | Proves the pipeline end to end on generic invoices | Before the event |
| Topic layer | `<fill in on the day: schema, rule pack, data generator, signature screens>` | During the event |

**Third-party libraries with copyleft licences:** the agent uses PyMuPDF 1.25.1 (`agent/requirements.txt`) for PDF text, fonts, metadata and revision history. PyMuPDF is AGPL-3.0, so this project is offered under AGPL-compatible terms for the event. For production, pdfminer.six (MIT) with pypdf (BSD) is the permissive swap; only `agent/app/pdf.py` and the test fixtures that build PDFs would change.

**AI tools used (rule 6):** Claude Code, used to scaffold and review code. Every design decision is documented in ARCHITECTURE.md and can be explained by the team.

**Models used at runtime (rule 4):** an ordered fallback chain set in `.env`: Groq-hosted `gpt-oss-120b`, Google Gemini, Mistral, local `llama3.2` through Ollama, and a deterministic mock. Prompts live in `agent/app/schemas/` and `agent/app/explain.py`.

**Data (rule 5):** synthetic only. Nothing here comes from customers, production systems or any employer.
