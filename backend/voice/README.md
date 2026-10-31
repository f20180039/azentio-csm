# Renewal Desk voice service

FastAPI service that runs the renewal call: text mode (`/v1/text-call`, `/v1/text-turn`) and live voice over WebRTC (`POST /api/offer`).
The live pipeline is browser mic → Silero VAD + Smart Turn → Groq Whisper (`whisper-large-v3-turbo`) → Groq `openai/gpt-oss-120b` with the seven renewal tools → edge-tts (`en-IN-NeerjaNeural`) → browser speaker.
Every tool goes through the renewals API, which decides what is allowed; the transcript is posted to `/renewals/calls/{id}/turns` and the call is ended when the client disconnects.

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --port 7861
.venv/bin/python -m pytest -q
```

`POST /api/offer` takes `{sdp, type, pc_id?, requestData: {callId}}` for a call started through the API (`POST /api/v1/renewals/calls` as an analyst) and returns the SDP answer. The agent speaks the call's greeting first.

## Env

Read from the process env, then `../.env`:

| Variable | Default |
|---|---|
| `GROQ_API_KEY` | required (speech to text, and the Groq links) |
| `GEMINI_API_KEY` / `MISTRAL_API_KEY` | optional; a link without its key is skipped |
| `RENEWALS_API_BASE` | `http://localhost:8080/api/v1` |
| `RENEWALS_API_USER` / `RENEWALS_API_PASSWORD` | `voice` / `voice` |
| `VOICE_STT_MODEL` | `whisper-large-v3-turbo` |
| `VOICE_LLM_CHAIN` | `groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b,gemini:${GEMINI_MODEL:-gemini-2.5-flash},mistral:${MISTRAL_MODEL:-mistral-small-latest}` |
| `VOICE_TTS_VOICE` | `en-IN-NeerjaNeural` |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM` / `TWILIO_ALLOWED_TO` / `PUBLIC_BASE_URL` | optional; all five turn on phone calls |

## Model chain

The agent's model is the first link in `VOICE_LLM_CHAIN` that is not resting. A daily-cap 429 rests a link until its `Retry-After` (1 h if absent), any other 429 for `Retry-After` capped at 60 s (20 s if absent), a 5xx or timeout for 30 s, a 401/403/404 for 1 h; a 400/422 about tool-call format just passes this request to the next link. With every link resting the text endpoint answers 429 `LLM_DAILY_LIMIT` (all daily caps) or 502, and a live call speaks "Sorry, give me a moment."; after three such fallbacks with no reply in between it hands the call off (`LLM_UNAVAILABLE`), says "I'll ask a colleague to call you back shortly." and ends the call

Text calls go through `ChainChatClient` (`app/llm_chain.py`). Live calls put one Pipecat LLM service per link behind Pipecat's `LLMSwitcher`, with a strategy that rests the link on those errors, switches, and re-runs the failed turn on the new link; each turn starts on the first rested link, so the chain returns to the primary once its cooldown ends. Both share one state, served without keys at `GET /v1/llm/status` (`{active, links: [{name, available, cooldownUntil, lastError}]}`) and shown on the dashboard as "Model in use".

Per-provider shaping: `reasoning_effort: low` only for Groq gpt-oss models; Gemini needs a `thought_signature` on every tool call in the history (its own are kept, others get Google's documented skip value); Mistral rejects that field (422) and gets tool-call ids normalised to 9 alphanumerics, mapped back on the reply.

## Phone calls (Twilio)

The agent can also call a real phone: Twilio dials the number and streams the call audio to `WS /ws/twilio`, which runs the same pipeline at 8 kHz μ-law. The browser call stays the backup.

1. In Twilio: note the Account SID and Auth Token, get a Twilio number, and verify the mobile you will call (trial accounts can only call verified numbers, play a trial notice and wait for a key press).
2. `brew install cloudflared`, then `cloudflared tunnel --url http://localhost:7861` and copy the `https://….trycloudflare.com` URL (new on every run).
3. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` (the Twilio number), `TWILIO_ALLOWED_TO` (comma-separated E.164) and `PUBLIC_BASE_URL` (the tunnel URL) in `../.env`, and restart this service.
4. `GET /v1/phone/allowed` now reports `configured: true`; on a call page pick the masked number and click **Call a phone**.

Only Twilio's endpoints are public. A request that arrives through the tunnel (it carries `Cf-Connecting-Ip`, `Cf-Ray`, `X-Forwarded-For` or `Forwarded`) may reach only `/twilio/twiml` (Twilio fetches the call instructions there, served only for a call this process is dialling; trial accounts refuse instructions sent inline), `/ws/twilio` and `/health`; everything else answers 403 `LOCAL_ONLY`, so dialling, the browser call and the text endpoints work only from this machine. The stream itself is accepted only for a call this process dialled, with the matching Twilio call SID. One phone call runs at a time (409 `PHONE_BUSY`), and an ended call is not dialled again (409 `CALL_ENDED`). Before dialling, the service fetches `PUBLIC_BASE_URL/health` (2 s timeout) and answers 503 `TUNNEL_DOWN` if the tunnel does not reach it. A Twilio error is passed on with any phone number in it masked.

**End call on the web does not hang up the phone**, so the call page disables it while a phone call rings or is live. The phone call ends when the agent calls `end_call` or the customer hangs up. **Cancel** only stops the page waiting (it also gives up by itself after 2 minutes of ringing); **Connect voice** stays available as the browser backup.

## Support desk by phone

Customers can ring the front-desk agent on the Twilio number, and the support call page can ring a phone for you. Both start a support call with channel `PHONE` and stream its audio to `WS /ws/twilio/support`, which runs the same support pipeline as the browser microphone at 8 kHz.

1. Do steps 1 and 2 of **Phone calls (Twilio)** above: Account SID and Auth Token, a Twilio number, `cloudflared tunnel --url http://localhost:7861`. On a trial account, verify your mobile under **Phone Numbers → Verified Caller IDs**. Trial accounts take calls only from verified numbers, and play a trial notice before your webhook runs.
2. In the Twilio console, open **Phone Numbers → Manage → Active numbers →** your number. Under **Voice Configuration**, set **A call comes in** to *Webhook*, URL `{PUBLIC_BASE_URL}/twilio/support/incoming`, method `HTTP POST`, and save. The tunnel URL changes on every `cloudflared` run, so update this URL each time.
3. In `../.env`: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `PUBLIC_BASE_URL` are enough to answer calls. "Call a phone" also needs `TWILIO_FROM` and `TWILIO_ALLOWED_TO`. Set `HUMAN_AGENT_NUMBER` (E.164) to transfer escalations to a person. Leave it empty and phone callers get the call-back with `HELPLINE_NUMBER`. Restart this service.
4. Ring the number: the agent greets you, and the call appears on the customer service desk as **Phone**. Or open a new support call and, under **Customer audio**, pick a masked number and click **Call a phone** (`POST /support/phone-call`, local only, allow-listed numbers, one phone call at a time).

**Signature check.** Every request to `/twilio/support/incoming` must carry a valid `X-Twilio-Signature`: base64 of an HMAC-SHA1, keyed with `TWILIO_AUTH_TOKEN`, over `PUBLIC_BASE_URL` + the path (+ query) followed by each POST parameter name and value, sorted by name. A wrong or missing signature, or Twilio not configured, gets 403 and starts nothing. So `PUBLIC_BASE_URL` must be exactly the URL set in the console. The media stream is accepted only for a call this process answered or dialled, with the matching `CallSid`. The caller's number (`From`) is sent to the simulator as `caller_ref`, so failed verifications lock per caller.

On escalation with a `HUMAN_AGENT_NUMBER`, the agent says it is connecting them. After `HANDOFF_TRANSFER_DELAY_SECS` (6 s), Twilio redirects the live call to that number, which ends the stream.

## Headless check

With the API (`ENFORCE_CALLING_HOURS=false`) and this service running:

```bash
.venv/bin/python scripts/headless_call.py --policy HF-2291-0457
```

It starts a call, plays synthesised customer speech over WebRTC, prints the latency from the end of each customer line to the first agent audio, and the call's audit events.

## Latency (2026-10-29, Smart Turn + VAD `stop_secs=0.2`, user-turn stop timeout 2 s)

End of customer speech → first agent audio, measured at the client, one call on HF-2291-0457.

| Customer says | Latency |
|---|---|
| yes speaking | 1030 ms |
| fourteenth March nineteen eighty (verify + get_policy) | 2090 ms |
| can you give me a discount (quote_renewal check) | 3233 ms |

Second run, same settings and policy:

| Customer says | Latency |
|---|---|
| yes speaking | 1490 ms |
| fourteenth March nineteen eighty | 3214 ms |
| can you give me a discount | 1732 ms |

p50: **1732 ms**.

First run p50: **2090 ms**. Greeting audio arrives about 0.9 s after the WebRTC connection is up.
Before (Pipecat default stop timeout 5 s, VAD `stop_secs=0.8`, options fetched after every verify): p50 2558 ms over two calls, worst turn 11.4 s while Smart Turn waited on a spoken date.
