# Case Intelligence Starter

Reusable scaffolding for document-driven review workflows. Documents come in, structured data comes out, a configurable rules engine scores each case, an LLM explains the findings with quotes it must prove, and a human reviewer decides. Every step lands in a tamper-evident audit log.

Design and contracts: [ARCHITECTURE.md](ARCHITECTURE.md). Per-service details: [api/](api/README.md), [agent/](agent/README.md), [voice/](voice/README.md), [web/](web/README.md).

**Renewal Desk** (problem #05, CSM voice agent) is the topic built on top: an insurance renewal call that an analyst starts from the Renewals queue and the customer takes in the browser. The agent talks, but the API decides what it may offer.

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
| Voice | http://localhost:7861/health |
| Postgres | localhost:5433 (host 5432 is left for a local Postgres) |

Sign in as `analyst/analyst`, `reviewer/reviewer` or `admin/admin`.

**Browser voice calls need the voice service run natively.** Compose starts the voice container, which serves typed calls and `/health`, but WebRTC audio from a Docker Desktop container on macOS does not connect without host networking or a TURN server. For a spoken call, keep compose for the API, web app and database, stop the container (`docker compose stop voice`) and run the voice service natively on port 7861 as in step 4 below, with `RENEWALS_API_BASE=http://localhost:8080/api/v1`.

**Renewal call:** open Renewals in the web app, pick a policy and start the call. The voice agent needs `GROQ_API_KEY` in `.env` (free key at https://console.groq.com/keys) and internet, because speech uses the Edge read-aloud service. The API refuses calls outside calling hours; set `ENFORCE_CALLING_HOURS=false` in `.env` to demo at any time. The voice service logs in to the API as `voice/voice` (`RENEWALS_API_USER`, `RENEWALS_API_PASSWORD`).

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
4. Start the voice service: `cd voice && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && GROQ_API_KEY=... .venv/bin/uvicorn app.main:app --port 7861`. Start the API with `ENFORCE_CALLING_HOURS=false` to call outside calling hours.
5. Start the web app: `cd web && npm run dev`. Use `npm run dev:mock` for the UI alone, on example data.

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
| voice | `.venv/bin/pytest -q` | Tool wiring and refusals, call brain loop, prompt, spoken-number handling, config, HTTP endpoints, pipeline setup |
| web | `npm test` | API error handling, response shapes, finding card, evidence highlight, mock-mode flow, renewals queue and call screen |

## Voice latency

End of customer speech to first agent audio, measured at the client with `voice/scripts/headless_call.py` on policy HF-2291-0457 (details in [voice/README.md](voice/README.md)).

| Customer says | Latency |
|---|---|
| yes speaking | 1030 ms |
| fourteenth March nineteen eighty (verify + get_policy) | 2090 ms |
| can you give me a discount (quote_renewal check) | 3233 ms |

p50 over those three turns: 2.1 s. A second run with the same settings gave 1490, 3214 and 1732 ms, p50 1.73 s. Greeting audio starts about 0.9 s after the WebRTC connection is up.

## Declaration of reused components

Rule 3 of Azentio.ai Build Labs asks for this. The rows marked "Before the event" were built as generic scaffolding with no knowledge of the problem statement. The rows marked "During the event" are Renewal Desk work and are not pre-built.

| Component | What it is | Built |
|---|---|---|
| `api/` | Spring Boot service: cases, upload dedupe, Postgres job queue, rule-pack engine, scoring and routing, review decisions, audit hash chain, RBAC | Before the event |
| `agent/` | FastAPI service: PDF text extraction, hidden-text and injection checks, PII masking, LLM gateway with fallback, quote verification, eval harness | Before the event |
| `web/` | React reviewer app: queue, case workspace, audit view, rule packs | Before the event |
| `agent/app/voice/tts.py` | Text to speech (edge-tts, ElevenLabs), copied and trimmed from the team member's own earlier project solarfile-reels (private repo, access on request; `backend/app/pipeline/tts.py`, commit `f089eaa`, Aug 2026) | Before the event, for a different project |
| `demo` rule pack and `samples/` | Proves the pipeline end to end on generic invoices | Before the event |
| Topic layer: Renewal Desk | The `renewals` package in `api/` (call state, identity check, discount and offer limits, handoff, audit), the `voice/` service, the web Renewals and Call pages, and `agent/datagen/renewals.py` (synthetic policies) | During the event (29 Oct 2026) |
| `voice/app/edge_tts_service.py` | Pipecat text-to-speech service around edge-tts, ported from a throwaway latency spike written during the event (29 Oct 2026). Event work, not pre-built | During the event (29 Oct 2026) |

**Third-party libraries with copyleft licences:** the agent uses PyMuPDF 1.25.1 (`agent/requirements.txt`) for PDF text, fonts, metadata and revision history. PyMuPDF is AGPL-3.0, so this project is offered under AGPL-compatible terms for the event. For production, pdfminer.six (MIT) with pypdf (BSD) is the permissive swap; only `agent/app/pdf.py` and the test fixtures that build PDFs would change.

**Third-party libraries in the voice stack** (licences read from the installed package metadata):

| Library | Version | Licence | Used for |
|---|---|---|---|
| Pipecat (`pipecat-ai`) | 1.12.0 | BSD-2-Clause | Voice pipeline: WebRTC transport, Groq services, turn handling |
| `@pipecat-ai/client-js` | 1.13.1 | BSD-2-Clause | Browser client for the voice call |
| `@pipecat-ai/small-webrtc-transport` | 1.10.8 | BSD-2-Clause | Browser WebRTC transport |
| edge-tts | 7.3.1 | LGPL-3.0 (one file, `srt_composer.py`, is MIT) | Speech synthesis, used as an unmodified dependency. It calls Microsoft's online Edge read-aloud service, so it needs internet |
| Silero VAD (`silero_vad.onnx`) | bundled in the pipecat-ai 1.12.0 wheel | The package metadata gives no licence for the weights. Upstream (snakers4/silero-vad) publishes MIT; not verified from the install | Local voice activity detection, Pipecat default |
| Smart Turn v3.2 (`smart-turn-v3.2-cpu.onnx`) | bundled in the pipecat-ai 1.12.0 wheel | The package metadata gives no licence for the weights. Upstream (pipecat-ai/smart-turn) publishes BSD-2-Clause; not verified from the install | Local end-of-turn detection, Pipecat default |

Both models run locally on CPU through onnxruntime 1.24.4 (MIT).

**AI tools used (rule 6):** Claude Code, used to scaffold and review code. Every design decision is documented in ARCHITECTURE.md and can be explained by the team.

**Models used at runtime (rule 4):**
- Document pipeline (`agent/`): an ordered fallback chain set in `.env`: Groq-hosted `gpt-oss-120b`, Google Gemini, Mistral, local `llama3.2` through Ollama, and a deterministic mock. Prompts live in `agent/app/schemas/` and `agent/app/explain.py`.
- Renewal voice agent (`voice/`): Groq `whisper-large-v3-turbo` (speech to text), an ordered chain of free models for the conversation and tool calls (`VOICE_LLM_CHAIN`, default Groq `openai/gpt-oss-120b` then `openai/gpt-oss-20b` with reasoning effort low, then Gemini and Mistral; a link that hits a rate limit, outage or timeout rests and the next one answers, see `voice/README.md`), edge-tts `en-IN-NeerjaNeural` (speech), and Silero VAD with Smart Turn (local turn detection). Prompts live in `voice/app/prompt.py`. No Anthropic models are used at runtime.

**Data (rule 5):** synthetic only. Nothing here comes from customers, production systems or any employer.
