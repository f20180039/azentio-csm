# Azentio-CSM: customer service voice agent (problem #05)

A voice agent for a bank's customer service line, built for the Azentio.ai Build Labs hackathon on synthetic data. It is a prototype: it is not certified for any regulatory compliance and has not run against real customers or production systems.

Design and contracts: [ARCHITECTURE.md](ARCHITECTURE.md). Per-service details: [backend/api/](backend/api/README.md), [backend/voice/](backend/voice/README.md), [frontend/](frontend/README.md).

## What it does

A customer phones the bank's service line and speaks naturally. The front-desk agent:
- works out what they want: loan application status, repayment, account, service request, product question, complaint, insurance. It handles several requests in one call and asks a clarifying question when the request is unclear;
- verifies them by registered mobile number and date of birth before anything personal. Three failures lock verification, and another customer's record is refused **by the bank simulator**, not just by the prompt;
- answers only from the simulated bank systems and the approved FAQ. Every figure it says appears in that turn's retrieved data;
- raises service requests and complaints with reference numbers, escalates fraud and unauthorised debits to a human, and politely declines and **routes** anything unsupported;
- shows every step on the operator panel: the recognised speech, intents, verification status, the data each reply used, the reply text and the history.

| Service | Path | Port |
|---|---|---|
| Voice agent (Pipecat, Groq Whisper and LLM, Edge voice) | `backend/voice` | 7861 |
| Bank simulator: loan applications, loan accounts, core banking, tickets, insurance, FAQ | `backend/simulator` | 8090 |
| System of record: calls, turns, audit log, Renewal Desk (FastAPI, SQLite) | `backend/api` | 8080 |
| Operator panel (React) | `frontend` | 5173 |

**Three ways in, one agent:**
- the browser microphone (**Support desk → Start a call → Microphone**);
- recorded audio files (**Upload audio**, `POST /sim/audio`, or `scripts/simulate_audio.py`);
- typed turns (`POST /support/text-turn`).

All three use the same speech front end and the same agent, and record the same turn data.

**Speech front end** (measured in [docs/stt-benchmark.md](docs/stt-benchmark.md) on Indian, British, Nigerian and American voices, clean and in café noise):
- Silero voice detection tuned so pure noise never reaches speech-to-text;
- a banking-vocabulary prompt for Whisper (word errors 4.6% → 3.7%; in noise 7.3% → 5.1%);
- a filter for words Whisper invents from noise;
- repair of spoken references ("S R four zero one zero two" → `SR-40102`);
- no noise reduction, because it tripled errors in noise.

**Renewal Desk**, the earlier outbound insurance-renewal agent, is still here (Renewals in the web app). It is planned as a specialist the front desk can hand renewal calls to.

## Quick start without Docker

```bash
cp .env.example .env            # add GROQ_API_KEY (free at console.groq.com); never an Anthropic key
scripts/dev-up.sh               # API + simulator + voice + web; creates missing venvs; no database server needed
open http://localhost:5173/support   # sign in as analyst/analyst
scripts/dev-down.sh
```

If a port is busy, the script names the process. You can also pick other ports with `API_PORT=8081 SIM_PORT=8091 VOICE_PORT=7862 WEB_PORT=5174 scripts/dev-up.sh`.

## Recorded-audio simulation

`POST /sim/audio` (voice service) takes multipart `files`, one file per customer turn, in order. It also takes an optional `call_id` to continue a call, and `speak=false` to skip reply audio. Any format ffmpeg/PyAV reads works (WAV, MP3, M4A, OGG, FLAC, WebM).

```json
{"call_id": "…", "ended": false, "outcome": null,
 "turns": [{"file": "t1.wav", "transcript": "When is my next EMI?", "no_speech": false, "speech_secs": 1.81, "upload_bytes": 39395,
            "intents": ["REPAYMENT"], "verified": false, "tool_trace": [{"name": "…", "args": {}, "result": {}}],
            "retrieved": {"<tool>": {}}, "refs": [], "reply_text": "…", "reply_audio_b64": "<mp3>", "latency_ms": 2960}]}
```

- A file with only silence or noise comes back with `"no_speech": true` and no reply.
- `python backend/voice/scripts/simulate_audio.py <files|folders>` writes a markdown and JSON report.
- `python -m eval.run_scenarios [--audio --accent in|gb|ng|us --condition clean|noisy | --full]`, run from `backend/voice`, scores the scripted #05 scenarios: intents, verification, required and forbidden phrases, tickets, routing, and disclosure before verification (target 0).

## Demo script (seed customers in `backend/simulator/data/seed`)

| Scenario | Say | Expect |
|---|---|---|
| Loan application status | "I applied for a personal loan last week, what's the status? And when is my first instalment?" then 98765 00001 / 12 April 1990 | Document verification, never "approved". No schedule until disbursal. |
| Repayment, then correction | "When is my next EMI?" then 98765 00002 / 3 Nov 1985, then "No, I meant my vehicle loan" | ₹12,450 personal loan, then ₹9,800 vehicle loan, with no re-verification. |
| Service request, then unsupported | "Send me my loan statement", then "Can you book me a flight to Dubai?" | A ticket SR-… read back, and a polite refusal plus a routed query RQ-…. |
| Failed transaction | 98765 00004 / 14 Feb 1978, "my transfer failed" | Recorded status only, no guessed cause. Offers a complaint. |
| Someone else's loan | Verified as 98765 00002, "what about loan VL-31007?" | Declined; nothing disclosed. |
| Unauthorised debit | 98765 00008 / 9 Mar 1982, "I didn't make this ₹48,999 payment" | Complaint CMP-… plus escalation to a human. |
| Three wrong dates of birth | any mobile, wrong DOB × 3 | Locked; nothing personal shared. |

## Run it

**Without Docker (recommended for the demo):** `scripts/dev-up.sh` creates any missing virtualenvs and `node_modules`, then starts all four services and waits for their health checks. `scripts/dev-down.sh` stops them. To run one service by hand:

| Service | Command (from its folder) |
|---|---|
| System-of-record API, 8080 | `backend/api`: `ENFORCE_CALLING_HOURS=false .venv/bin/python -m uvicorn app.main:app --port 8080` (SQLite at `API_DB_PATH`, default `data/runtime/api.db`) |
| Bank simulator, 8090 | `backend/simulator`: `.venv/bin/python -m uvicorn app.main:app --port 8090` |
| Voice, 7861 | `backend/voice`: `.venv/bin/python -m uvicorn app.main:app --port 7861` (reads `.env` from the repo root) |
| Web, 5173 | `frontend`: `npm run dev`, or `npm run dev:mock` for the UI on example data with no backend |

**With Docker:** `docker compose up --build` (being verified end to end by task C7). Browser microphone calls from a Docker Desktop container on macOS do not connect without host networking or a TURN server, so for spoken calls run the voice service natively.

**Keys and models.** Copy `.env.example` to `.env`.
- `GROQ_API_KEY` is the one key you need: speech to text (Whisper) and the first model in the chain. It is free at https://console.groq.com/keys.
- `GEMINI_API_KEY` and `MISTRAL_API_KEY` are optional fallbacks. A local Ollama (`ollama pull llama3.2`) is the last fallback and needs no key or internet.
- `VOICE_LLM_CHAIN` sets the order; see [Models used at runtime](#declaration-of-reused-components).
- Anthropic models are refused by the voice agent's configuration.

**Escalation settings:** `HUMAN_AGENT_NUMBER` is the number a phone call is transferred to, and `HELPLINE_NUMBER` is spoken to browser callers.

**Phone calls (optional).** The agent can dial a Twilio-verified mobile instead of using the browser mic.
- Set the `TWILIO_*` and `PUBLIC_BASE_URL` values in `.env` (see `.env.example`).
- Run `cloudflared tunnel --url http://localhost:7861` and put its https URL in `PUBLIC_BASE_URL`.
- Only the Twilio stream is reachable through the tunnel; every other voice endpoint answers 403 `LOCAL_ONLY` there.
- Details are in `backend/voice/README.md`.

## Safety and guard rails

Each rule is enforced in code, not only in the prompt, and has tests.

| Rule | Where |
|---|---|
| Nothing personal before verification by registered mobile and date of birth | voice tool layer refuses with no HTTP call; the simulator requires a session token on every personal endpoint |
| No verification attempt spent on details the caller has not given | voice tool layer (needs a 10-digit mobile and a real date) |
| 3 wrong attempts lock that customer for 15 minutes, across calls | simulator (`LOCKED`) |
| One caller failing for 3 different customers, or 6 times in 30 minutes, is blocked, and a security escalation is raised | simulator (`CALLER_BLOCKED`, `SECURITY` escalation on the operator panel) |
| A verified caller cannot read another customer's record | simulator (`NOT_YOUR_RECORD`) |
| Figures are spoken only from tool results, with amounts in their `*_spoken` form | prompt, plus spoken copies added by the tool layer |
| Product questions answered only from the approved FAQ; no match means "no approved information" and a routed query | simulator FAQ search with a score threshold; prompt |
| Every unsupported request is routed, even if the model forgets | backstop in `SupportBrain`: a turn the intent detector labels unsupported is routed if the model did not route it |
| The agent never offers what its tools cannot do | prompt |
| Renewals: date-of-birth lockout, offer and discount limits, hand-off after repeated out-of-policy requests, calling hours | system-of-record API, ported from the earlier Java service with its tests |
| Tamper-evident audit trail | hash-chained audit log in the system-of-record API (`/api/v1/audit/verify`) |

## Escalation to a person

- **A first plain request for a person is not a hand-over.** The tool refuses it (`ASK_FIRST`); the agent asks what the caller needs and tries to help. A second request hands over.
- **The agent hands over unasked** when the caller is unhappy with the help (`DISSATISFIED`), when it could not answer or act after trying (`UNRESOLVED`), and at once for fraud, unauthorised transactions or distress (`SENSITIVE`).
- **Phone call:** after the agent says it is connecting them, Twilio transfers the live call to `HUMAN_AGENT_NUMBER`. This is wired for both Renewal Desk phone calls and support desk phone calls (callers ringing the Twilio number, or "Call a phone" on a support call). With `HUMAN_AGENT_NUMBER` empty, a phone caller gets the call-back below instead.
- **Browser:** an escalation record with an `ESC-` reference. The caller hears that a colleague will call back, plus the helpline number.

## Demo-day checklist

- **Headset:** use one for microphone calls, because the agent can hear itself through laptop speakers.
- **Reset between runs:** `curl -u ops:ops -X POST http://localhost:8090/v1/ops/reset` clears lockouts, caller blocks and new tickets.
- **Model quota:**
  - Groq's free tier allows 8,000 tokens per minute per model. The chain fails over to Gemini, Groq 20b, Mistral and local Ollama, so replies keep coming.
  - Check `GET http://localhost:7861/v1/llm/status` to see which link is answering.
  - Don't run `python -m eval.run_scenarios --full` or `eval.simulate` before the demo: they share the quota.
- **Speech to text is Groq Whisper only.** If Groq is down, use typed turns or recorded audio, which go through the same agent.
- **Phone calls:** after restarting `cloudflared`, restart the voice service, because `PUBLIC_BASE_URL` changes. A Twilio trial account plays a preamble and waits for a key press.

## Tests

| Service | Command | Tests | Coverage |
|---|---|---|---|
| Voice | `cd backend/voice && .venv/bin/python -m pytest -q` | 369 | support tools and verification gate, support brain and routing backstop, escalation rules, intents, speech front end and reference repair, recorded-audio simulation, barge-in turn gate, model chain, phone transfer, renewal agent |
| Bank simulator | `cd backend/simulator && .venv/bin/python -m pytest -q` | 108 | verification, cross-call and per-caller lockout, record ownership, loan/account/insurance records, tickets and complaints, ops, FAQ search |
| System-of-record API | `cd backend/api && .venv/bin/python -m pytest -q` | 91 | support call contract, renewal guard rails, roles, dashboard from data, audit hash chain |
| Web | `cd frontend && npm test && npx tsc --noEmit` | 94 | operator panel, live call view, uploads, search, dropdowns, sign-in, renewals and dashboard |

The scored scenario evaluation (`backend/voice/eval/run_scenarios.py`) and its results are described in [Recorded-audio simulation](#recorded-audio-simulation). The accent and noise speech-to-text benchmark is in [docs/stt-benchmark.md](docs/stt-benchmark.md).

## Voice latency

**Support desk, typed turns through the live agent:** p50 1.7 s, p95 3.4 s from request to reply text (31 Oct, two live scenarios, Groq first in the chain). Speech adds the speech-to-text upload (about 0.25 s, see the benchmark) and the 1 s pause that waits for the caller to finish (`VOICE_TURN_SETTLE_SECS`).

**Renewal Desk**, end of customer speech to first agent audio, measured at the client with `backend/voice/scripts/headless_call.py` on policy HF-2291-0457 (details in [backend/voice/README.md](backend/voice/README.md)):

| Customer says | Latency |
|---|---|
| yes speaking | 1030 ms |
| fourteenth March nineteen eighty (verify + get_policy) | 2090 ms |
| can you give me a discount (quote_renewal check) | 3233 ms |

## Declaration of reused components

Rule 3 of Azentio.ai Build Labs asks for this. "Before the event" means built as generic scaffolding with no knowledge of the problem statement. Everything for problem #05 was built during the event (29–31 Oct 2026).

| Component | What it is | Built |
|---|---|---|
| `backend/voice/` support desk | Front-desk agent: tools, verification gate, prompt, intents, speech front end, recorded-audio simulation, escalation, live pipeline | During the event (Anshuman) |
| `backend/simulator/` | Bank simulator: seed data, verification and lockouts, records, tickets, FAQ search | During the event (Chirag; C3–C5 by Anshuman's agents at the team lead's request) |
| `backend/voice/eval/` content | FAQ entries, 12 scenarios, 60 labelled utterances, accent and noise renderer | During the event (Pavan) |
| `backend/api/` | FastAPI + SQLite system of record: support call records, renewal calls with guard rails, audit hash chain. Replaced the starter's Spring Boot service on 31 Oct; the document case pipeline was dropped with it | During the event (Chirag, hardened by Anshuman) |
| `frontend/` | React operator panel (support desk, live call, search, sign-in). The routing, session and dashboard shell came from the starter | Shell before the event; panel during the event |
| Renewal Desk (renewal routes in `backend/api/`, the renewal agent in `backend/voice/`, the Renewals and Call pages) | Outbound renewal agent with offer limits and hand-off | During the event (29 Oct 2026) |
| `frontend/public/favicon-*.png` | The Azentio favicon, copied from azentio.com for the app's tab icon | Copied during the event |

**Third-party libraries in the voice stack** (licences read from the installed package metadata):

| Library | Version | Licence | Used for |
|---|---|---|---|
| Pipecat (`pipecat-ai`) | 1.12.0 | BSD-2-Clause | Voice pipeline: WebRTC transport, Groq services, voice activity detection |
| `@pipecat-ai/client-js` | 1.13.1 | BSD-2-Clause | Browser client for the voice call |
| `@pipecat-ai/small-webrtc-transport` | 1.10.8 | BSD-2-Clause | Browser WebRTC transport |
| edge-tts | 7.3.1 | LGPL-3.0 (one file, `srt_composer.py`, is MIT) | Speech synthesis, as an unmodified dependency; needs internet |
| Silero VAD (`silero_vad.onnx`) | bundled in pipecat-ai 1.12.0 | Upstream (snakers4/silero-vad) publishes MIT; not verified from the install | Local voice activity detection |

**AI tools used (rule 6):** Claude Code, to scaffold, review and test code, and to run sub-agents on scoped tasks. The design decisions are documented in `docs/` and `ARCHITECTURE.md`, and the team can explain them.

**Models used at runtime (rule 4):**
- **Speech to text:** Groq `whisper-large-v3-turbo` with a banking vocabulary prompt (see `docs/stt-benchmark.md`).
- **Conversation and tool calls:** an ordered chain of free models, `VOICE_LLM_CHAIN`. The default is Groq `openai/gpt-oss-120b`, then Gemini `gemini-3-flash-preview`, then Groq `openai/gpt-oss-20b`, then Mistral `mistral-small-latest`, then local Ollama `llama3.2`. A link that hits a rate limit, outage or timeout rests and the next one answers.
- **Intents:** Groq `openai/gpt-oss-20b` in JSON mode, with keyword rules as the fallback.
- **Speech:** edge-tts `en-IN-NeerjaNeural`.
- **No Anthropic models are used at runtime.** Prompts live in `backend/voice/app/support_prompt.py` (support desk) and `backend/voice/app/prompt.py` (renewals).

**Data (rule 5):** synthetic only. Nothing here comes from customers, production systems or any employer.
