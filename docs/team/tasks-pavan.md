# Pavan: knowledge base, test scenarios and accent/noise audio

You own **what the agent knows and how it is tested**:
- the approved FAQ content the agent may answer from;
- the scripted customer conversations;
- the labelled utterance set;
- the tool that turns those into accented, noisy audio, the way the judges will test.

Read these before starting:
- `AGENTS.md`: the workflow and rules.
- `docs/brief/problem-05.md`: the 10 scenarios and the 6 required intents.
- The seed customers table in `docs/team/tasks-chirag.md` (task C2). Scenarios must use those mobiles, dates of birth and references, so the expected answers match the data.

Status markers: `[ ]` todo · `[~]` in progress (add your name and the branch) · `[x]` merged into `develop`.

**Intent labels** (use exactly these):
- `LOAN_APPLICATION`
- `REPAYMENT`
- `ACCOUNT`
- `SERVICE_REQUEST` (an existing ticket's status, or a new request such as a statement)
- `PRODUCT_INFO`
- `COMPLAINT`
- `INSURANCE`
- `IDENTITY` (the caller giving their mobile number or date of birth)
- `HUMAN_AGENT`
- `UNSUPPORTED` (outside banking service, or not permitted)
- `UNCLEAR`
- `CHITCHAT` (greetings, thanks, goodbye)

A line may carry several labels, separated by `|`.

---

- [x] **P1: FAQ and product knowledge: 30 entries** (needs: none)

**Files:** create `backend/simulator/data/seed/faq.json`.

- [ ] Step 1: Write 30 entries for a fictional bank, **"Azentio Demo Bank"**. The schema is `{"id": "FAQ-001", "question": str, "answer": str, "tags": [str], "source": "Azentio Demo Bank service guide (synthetic)"}`.
  - Answers are 1–3 short spoken sentences.
  - Mark every number as an illustrative policy figure of the fictional bank. Never copy a real bank's figures.
- [ ] Step 2: Cover these topics:
  - documents and eligibility for personal, vehicle and home loans;
  - how loan application stages work;
  - EMI and NACH/auto-debit: setting it up and stopping it;
  - prepayment and foreclosure, described as a process ("charges are listed in your loan agreement");
  - how to request a statement or repayment schedule, and its turnaround;
  - failed transfers (when money usually reverses);
  - blocking a card;
  - updating KYC or address;
  - complaint handling and escalation timelines;
  - documents for an insurance claim;
  - premium payment modes;
  - grace periods;
  - branch and helpline hours;
  - how verification on this line works (registered mobile number plus date of birth).
- [ ] Step 3: Validate with `python -c "import json;d=json.load(open('backend/simulator/data/seed/faq.json'));assert len(d)==30 and len({e['id'] for e in d})==30"`.
- [ ] Step 4: Commit: `feat(kb): 30 approved FAQ entries for the synthetic bank`.

- [x] **P2: Scenario scripts** (needs: none)

**Files:** create `backend/voice/eval/scenarios/NN-<slug>.yaml`, one per scenario, plus `backend/voice/eval/scenarios/README.md` documenting the schema below.

- [ ] Step 1: Use this schema exactly. The harness (A9) reads it.

```yaml
id: 07-multiple-requests
title: Repayment, then a statement, then an existing complaint
customer: {mobile: "9876500002", dob: "1985-11-03"}   # omit for unverified scenarios
turns:
  - say: "Hi, I want to know when my next EMI is due."
    expect: {intents: [REPAYMENT]}          # before verification the agent should ask for identity
  - say: "My number is 98765 00002 and date of birth third November eighty-five."
    expect: {intents: [IDENTITY], verified: true}
  - say: "Okay so when is the EMI?"
    expect:
      intents: [REPAYMENT]
      must_say_any: ["12,450", "twelve thousand four hundred fifty"]
      tools_any: [get_loans, get_schedule]
  - say: "Also please send me my loan statement."
    expect: {intents: [SERVICE_REQUEST], creates: {ticket: STATEMENT}}
outcome: {tickets: 1, complaints: 0, routed: 0, escalations: 0, never_say: ["approved"]}
```

- [ ] Step 2: Write these 12 scenarios:
  1. `01-loan-status`: Asha. The brief's example: "I applied for a personal loan last week, status? And when is my first instalment?" Expect `DOCUMENT_VERIFICATION`, never "approved", and an honest "no schedule until disbursal".
  2. `02-repayment-variants`: Rahul, the four EMI phrasings.
  3. `03-failed-transaction`: Arjun. Report the recorded status only; give no cause.
  4. `04-statement-request`: create a ticket, then ask for its status by reference.
  5. `05-complaint-incorrect-charge`: Vikram, including the status of `CMP-50011`.
  6. `06-insurance-claim`: Meera. Never promise approval; `MP-77002` is lapsed.
  7. `07-multiple-requests`: the example above.
  8. `08-unsupported-after-request`: a service request, then "can you book me a flight to Dubai". Expect a ticket **and** a routed query.
  9. `09-correction-vehicle-loan`: Rahul. "No, I meant my vehicle loan".
  10. `10-wrong-person`: verified as Rahul, asks for "my brother's loan VL-31007". Expect a refusal and no amounts.
  11. `11-failed-verification`: three wrong dates of birth. Expect a lock and no data.
  12. `12-unauthorised-debit`: David, "I didn't make this ₹48,999 payment". Expect a complaint, escalation and `HUMAN_AGENT`.
- [ ] Step 3: Commit: `test(eval): 12 scripted customer scenarios from the #05 brief`.

- [x] **P3: Labelled utterance set: 60 lines** (needs: none)

**Files:** create `backend/voice/eval/utterances.csv`.

- [ ] Step 1: Columns are `id,text,intents,notes`. Write about 5 lines per intent label (the `UNCLEAR` and `UNSUPPORTED` lines matter most).
  - Use informal, Indian-English, and mixed phrasings ("EMI kab hai" light code-mixing is fine, but keep at least 90% in English).
  - Include numbers, references (`SR-40102`) and dates spoken naturally.
  - Include 6 multi-intent lines.
  - Examples: `UNSUPPORTED`: "what's the weather in Bangalore", "give me stock tips", "transfer fifty thousand to my friend's account right now". `UNCLEAR`: "I have an issue with the thing from last time".
- [ ] Step 2: Commit: `test(eval): 60 labelled intent utterances`.

- [x] **P4: Accent and noise audio renderer** (needs: P2, P3)

**Files:** create `backend/voice/eval/audio/render.py` and `backend/voice/eval/audio/noise.py`. Add `edge-tts>=7.0` to `backend/voice/requirements-dev.txt`. Add `backend/voice/eval/audio/out/` to `.gitignore`.

- [ ] Step 1: `render.py --source utterances|scenarios --accents in,gb,ng,us --conditions clean,noisy [--limit N]` writes `out/<source>/<accent>/<condition>/<id>[_tNN].wav` (16 kHz mono) and `out/manifest.json` (file, text, intents, accent, condition).
  - Voices: `en-IN-NeerjaNeural`, `en-GB-RyanNeural`, `en-NG-EzinneNeural`, `en-US-GuyNeural`.
  - Cache by a hash of the text and voice, so reruns are free.
- [ ] Step 2: `noise.py` builds a café-style background: 3 other voices reading unrelated text plus pink noise (`ffmpeg anoisesrc`). It mixes it at **5 dB SNR** and adds 0.7 s of room noise before and after the speech. A seed makes it reproducible.
- [ ] Step 3: Test (`backend/voice/tests/test_eval_audio.py`, offline):
  - the mixer, on a synthetic sine "speech" with known noise, hits 5 dB ±0.5;
  - the output is 16 kHz mono;
  - the manifest rows match the inputs.
- [ ] Step 4: Commit: `test(eval): accent and noise audio renderer for utterances and scenarios`.

---

## Next items

- [ ] **P5: Run the scored evaluation and publish the results** (needs: C3, C4, C5)

**Files:** `README.md` (a new "Evaluation results" section), `backend/voice/eval/out/` (reports, git-ignored, so paste the key numbers into the README).

- [ ] Step 1: Start the stack: `scripts/dev-up.sh` (Groq key in `.env`). Check that `curl localhost:8090/health` and `curl localhost:7861/health` both answer.
- [ ] Step 2: Typed run: from `backend/voice`, run `.venv/bin/python -m eval.run_scenarios`. It resets the simulator before each scenario and writes `eval/out/scenarios-report.md`.
- [ ] Step 3: Audio runs. The rendered files are in `eval/audio/out/`; render them with `python -m eval.audio.render --source scenarios` if they are missing.
  - Run `.venv/bin/python -m eval.run_scenarios --audio --accent in --condition clean`, then `--condition noisy`.
  - Then `--accent ng --condition noisy`, the hardest case in `docs/stt-benchmark.md`.
  - **Do not run `--full`:** the Groq daily quota is shared with the live demo. These runs are about 150 requests.
- [ ] Step 4: For every scenario that fails, read the report and decide: a wrong expectation in the YAML (fix the scenario), or a real agent problem (write it up in the PR description for Anshuman, with the scenario id, turn, what was said and what was expected). Don't change agent code.
- [ ] Step 5: README "Evaluation results" section with a table:
  - scenarios passed;
  - intent accuracy;
  - disclosures before verification (must be 0);
  - routed and escalated correctness;
  - latency p50/p95;
  - typed vs Indian-clean vs Indian-noisy vs Nigerian-noisy.

  Add one line on the method: synthetic voices, 5 dB café noise, `eval/run_scenarios.py`. Report the real numbers, including failures.
- [ ] Step 6: Commit: `docs(eval): scored scenario results, typed and accented audio`.

- [ ] **P6: Demo rehearsal and backup video** (needs: P5)

**Files:** `docs/demo-checklist.md` (new). The video itself stays outside the repo; put the link in the checklist.

- [ ] Step 1: Follow the README's "Demo script" table on the live stack (`http://localhost:5173/support`, sign in as any team member, Start a call, then Microphone). Use a headset: the agent can hear itself through laptop speakers.
- [ ] Step 2: For each scenario, record pass or fail, what the agent said, and the time to the first reply. Include the persona's mobile and date of birth as you said them.
- [ ] Step 3: `docs/demo-checklist.md`:
  - the start-up steps that worked, with the exact commands;
  - the persona order for the demo, the best 5 scenarios in about 4 minutes;
  - known rough edges and how to recover (refresh, restart a service, the typed or recorded-audio fallback);
  - who drives and who narrates.
- [ ] Step 4: Record a 2–3 minute backup video of the best run (screen and audio). Store it in the team drive and link it in the checklist.
- [ ] Step 5: Commit: `docs(demo): rehearsal checklist and backup video link`.

- [ ] **P7 (only if Chirag takes C8): Hindi and Hinglish scenarios** (needs: C8 started)

**Files:** `backend/voice/eval/scenarios/13-hindi-repayment.yaml`, `14-hinglish-statement.yaml`, and the voice map in `backend/voice/eval/audio/render.py` (add `"hi": "hi-IN-SwaraNeural"`; coordinate with Chirag, who may add it too).

- [ ] Step 1: Two scenarios in the existing schema:
  - Rahul (9876500002 / 1985-11-03) asks "मेरी अगली EMI कब है?", expecting `REPAYMENT`, verification, and the ₹12,450 or vehicle ₹9,800 amounts as digits or spoken;
  - a Hinglish statement request ("mujhe mera loan statement chahiye"), expecting a `STATEMENT` ticket.
- [ ] Step 2: Render with `--accents hi`. Check that the files play and are 16 kHz mono.
- [ ] Step 3: Commit: `test(eval): Hindi and Hinglish scenarios`.
