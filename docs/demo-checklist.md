# Demo checklist

A 5-minute live demo of the customer-service voice agent. The persona details are in [verification-lab.md](verification-lab.md).

## 15 minutes before

1. **Start everything:** `scripts/dev-up.sh`. It waits for all four health checks, then prints the panel URL.
2. **Clear old test data:** `curl -u ops:ops -X POST http://localhost:8090/v1/ops/reset` clears lockouts, caller blocks and new tickets.
3. **Check the models:** open `http://localhost:7861/v1/llm/status`. The first link should be available. If Groq is cooling down, the chain falls back to Gemini, then Groq 20b, Mistral and local Ollama, so replies still come.
4. **Check Ollama:** `ollama list` should show `llama3.2`. It's the offline last resort.
5. **Audio:** plug in a **headset**, because the agent can hear itself through laptop speakers. In the browser, allow the microphone for `localhost:5173`.
6. **Browser tabs:** the panel at `http://localhost:5173/support`, signed in as Anshuman (Admin), plus the Verification Lab.
7. **Quota:** don't run `python -m eval.run_scenarios --full` or `eval.simulate`. They share the Groq quota with the demo.

## The run (about 5 minutes)

| # | What you do | What the audience sees |
|---|---|---|
| 1 | **Start a call, then Microphone.** Say "When is my next EMI?" | The transcript appears, the Repayment chip and the speaking bubble show, and the agent asks for your mobile number and date of birth (nothing personal yet). |
| 2 | "My number is nine eight seven six five, zero zero zero zero two, born the third of November eighty-five." | The Verified badge turns green. The answer is ₹12,450, with a Retrieved card showing the loan record behind it. |
| 3 | "No, I meant my vehicle loan." | ₹9,800 from the vehicle loan, with no second verification. |
| 4 | "Please send me my loan statement." Then: "Can you book me a flight to Dubai?" | An `SR-…` ticket read back digit by digit, then a polite refusal with an `RQ-…` routed query. Both show on the Support desk's Tickets and Routed queries tabs. |
| 5 | Say goodbye and give a rating ("four"). | The rating is saved on the call; open **Insights** to show the rating, review queue and lessons. |
| 6 | **New call:** Rahul's number with three wrong dates of birth. | Locked. The right date is refused for 15 minutes, on this call and any new one. |
| 7 | **Upload audio:** drop `backend/voice/eval/audio/out/scenarios/ng/noisy/02-repayment-variants_t01.wav` (a Nigerian voice in café noise). | Transcribed and answered through the same agent: the accent and noise test the judges run. Play back the customer audio next to the transcript. |
| 8 | Close with the evidence: [stt-benchmark.md](stt-benchmark.md) and the scored evaluation in the README. | Measured accuracy by accent and noise, scenario pass rate, zero disclosures before verification. |

Optional extras if time allows:
- **Fraud:** David (98765 00008) says "I didn't make this ₹48,999 payment", giving a complaint plus escalation (Escalations tab).
- **Asking for a person:** "I want a person" (it asks what you need), then "just connect me" (escalation and helpline).
- **Wrong person:** verified as Rahul, ask about loan `VL-31007`; the simulator refuses.

## If something goes wrong

| Symptom | Fix |
|---|---|
| The agent says "trouble reaching our systems" | A model link is rate-limited and the next one is answering. Wait a few seconds and repeat. Check `/v1/llm/status`. |
| The transcript is gibberish or missing | Background noise. Move closer to the headset microphone and speak after the agent finishes. After two noisy attempts it asks you to repeat. |
| The microphone call won't connect | Reload the page (you stay signed in) and click Start talking again. Fallback: the **Upload audio** tab with the rendered files. |
| Locked out of a persona while demoing | Run the reset command above. |
| A service died | Run `scripts/dev-down.sh && scripts/dev-up.sh`. Check `.run/<service>.log`. |
| No internet | Speech-to-text (Groq) and the voice (Edge) need internet. Show the recorded backup video, plus the panel in mock mode (`cd frontend && npm run dev:mock`). |

## Roles

| Who | Does what |
|---|---|
| Anshuman | Drives the call and the panel |
| Chirag | Narrates the architecture and the simulator (verification, lockouts, records) |
| Pavan | Narrates the evaluation, accents and noise, and the FAQ knowledge base |

## Backup video

Record the run above once it works end to end, and keep the file outside the repo, in the team drive.
