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
| `GROQ_API_KEY` | required |
| `RENEWALS_API_BASE` | `http://localhost:8080/api/v1` |
| `RENEWALS_API_USER` / `RENEWALS_API_PASSWORD` | `voice` / `voice` |
| `VOICE_STT_MODEL` | `whisper-large-v3-turbo` |
| `VOICE_LLM_MODEL` | `openai/gpt-oss-120b` |
| `VOICE_TTS_VOICE` | `en-IN-NeerjaNeural` |

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

p50: **2090 ms**. Greeting audio arrives about 0.9 s after the WebRTC connection is up.
Before (Pipecat default stop timeout 5 s, VAD `stop_secs=0.8`, options fetched after every verify): p50 2558 ms over two calls, worst turn 11.4 s while Smart Turn waited on a spoken date.
