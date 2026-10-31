# Speech-to-text benchmark: accents and noise (31 Oct 2026)

This is how we chose the speech settings in `backend/voice/app/speech.py`. The full run (scripts, per-clip results, cached responses) lives in the team's `spikes/stt-bench` folder.

## Test set
- 12 banking utterances, each spoken in 4 edge-tts voices (Indian, British, Nigerian, American), giving 48 clean clips.
- The same 48 clips with café babble mixed in at 5 dB SNR (4 background voices plus pink noise).
- 6 noise-only clips.
- Every clip has 0.5–1 s of noise before and after the speech, at 16 kHz mono.
- **Caveat:** the speech is synthetic and there are only 24–48 clips per cell, so a gap of under about 2 points in word error rate (WER) is noise.

## Results (Groq, English pinned)

| Variant | Clips | WER | Keyword accuracy | Intent kept | p50 / p95 latency |
|---|---|---|---|---|---|
| Whole clip → turbo (before) | 96 | 4.3% | 93.1% | 99% | 0.26 / 0.53 s |
| VAD-trimmed → turbo | 96 | 4.6% | 92.8% | 99% | 0.24 / 0.40 s |
| **VAD-trimmed → turbo + domain prompt** | 96 | **3.7%** | **95.3%** | **100%** | 0.23 / 0.41 s |
| VAD-trimmed → large-v3 + prompt | 24 noisy + 12 clean | 2.1% | 94.7% | 97% | 0.31 / 0.40 s |
| Denoise → VAD → large-v3 + prompt | 24 noisy | 7.2% | 84.5% | 79% | 0.30 / 0.43 s |

The same 24 noisy clips (320 words) were run through each variant. Word errors per variant:

| Variant | Word errors |
|---|---|
| Baseline turbo | 19 |
| Turbo + prompt | 16 |
| **large-v3 + prompt** | **8** |
| Denoise + large-v3 | 23 |

**WER by accent, clean / noisy, with turbo + prompt:**

| Indian | British | Nigerian | American |
|---|---|---|---|
| 1.8 / 4.8% | 3.0 / 5.4% | 2.4 / 8.4% | 2.4 / 1.8% |

The Nigerian voice in noise is the weakest case: 11.4% WER at baseline, 8.4% with the prompt, and 2.5% with large-v3 plus the prompt. Reference numbers are the most-missed tokens; for example "SR-48213" comes back as "SR for 8213".

## What we changed, and why
- **Domain prompt:** the one clear win, on every accent and in noise.
- **Model:** we keep `whisper-large-v3-turbo` by default. `VOICE_STT_MODEL=whisper-large-v3` halves errors in noise for about +70 ms, so switch to it for a noisy room.
- **No noise reduction:** it tripled WER in noise and cut intent accuracy from 96% to 79%.
- **Voice detection:** `confidence 0.7, min_volume 0.6, start 0.2 s, stop 0.4 s`.
  - Stopping at 0.4 s instead of 0.2 s cuts live speech-to-text requests by about 30% (92 to 64 segments), because fewer sentences are split in two.
  - Silero rejected all pure-noise clips. It cannot reject café babble, because babble *is* speech (Silero confidence about 0.97). Background talkers can't be filtered at this layer.
- **Invented-transcript filter:** Groq's turbo always reports `no_speech_prob = 0`, so Whisper's classic rule never fires. We now drop:
  - a transcript that is only a phantom phrase ("thank you", "thanks for watching", …);
  - a segment with `avg_logprob < -0.7` or `no_speech_prob > 0.5`.

  On the cached responses this removed 5 of 20 false transcripts and lost no real speech.
- **Reference repair:** "SR for 8213" and "S R four zero one zero two" are normalised to `SR-48213` and `SR-40102` before the agent sees them.
- **Recorded audio:** silence trimming plus FLAC halves the upload. Pure-noise files are never sent to speech-to-text.

## Not covered
- Sarvam (no key was available).
- Real phone audio and real accents.
- RNNoise.
- large-v3 on the full set (the request cap was 400).

## Kannada (31 Oct 2026)

Task C8. The test set was 5 distinct caller turns from scenarios 13 and 14 (turn 2 is the same in both), rendered with edge-tts `kn-IN-SapnaNeural`, clean, 16 kHz mono, and sent through the recorded-audio path (VAD trim, FLAC, `whisper-large-v3-turbo`, `verbose_json`). There were 25 Groq speech-to-text requests in all. **Caveat:** this is one synthetic voice and 5 clips, with no noise and no real speakers.

| Turn (said) | Auto + English prompt | Auto + bilingual prompt (**shipped for `en,kn`**) | Pinned `kn` + Kannada prompt |
|---|---|---|---|
| ನನ್ನ ಮುಂದಿನ EMI ಯಾವಾಗ? | `Nana Mundina EMI, Yawa, Ka?` (romanised) | `ನನಮುಂದಿನ ಎಮೇಯಾವಾಗ.` | `ನನಮುಂದಿನ ಎಮೇಯಾವಾಗ?` |
| ನನ್ನ ಮೊಬೈಲ್ ನಂಬರ್ 98765 00002, ಹುಟ್ಟಿದ ದಿನಾಂಕ 3 ನವೆಂಬರ್ 1985. | **Telugu script**, digits garbled | `ನನ್ನ, ಮೋಬೈಲ್ ನಂಬರ್ ಒಂಬತ್ತು ಎಂಟು ಎಳು, ಆರು ಆಯದು ಸೊನ್ನೆ ×4 ಎರಡು, ಹುಟ್ಟಿದ ದಿನಾಂಕ ಮೂರು ನವೆಂಬರ್ ಒಂದು ಸಾವಿರ ಒಂಬಯನುರ ಎಂಬತ್ತಯಿದು.` | same as bilingual |
| ನನ್ನ ಮುಂದಿನ EMI ಎಷ್ಟು, ಯಾವಾಗ ಕಟ್ಟಬೇಕು? | `Nana Mundina M.A.S.T.U. Yawa G. Kattabeku.` (**dropped**, logprob −0.701) | `ನನವ್ ಮುಂದಿನ AMIASಟು ಯಾವಾಗ ಕಟ್ಟಬೇಕು.` | `ನನ್ನ ಮುಂದಿನ ಮೈಯೇಷ್ಟು ಯಾವಾಗ ಕಟ್ಟಬೇಕು.` |
| ನನಗೆ ನನ್ನ ಲೋನ್ ಸ್ಟೇಟ್‌ಮೆಂಟ್ ಬೇಕು | `NANGE NANNA LOAN STATEMENT BAKO.` | `ನನಗೆ ನನನ ಲೋನ್, ಸ್ಟೇಟ್ಮೆಟ್ ಬೇಕು.` | `ನನಗೆ ನನನ ಲೋಂ ಸ್ಟೇಟ್ಮೆಟ್ ಬೇಕು.` |
| ದಯವಿಟ್ಟು ಸ್ಟೇಟ್‌ಮೆಂಟ್ ರಿಕ್ವೆಸ್ಟ್ ಮಾಡಿ. | `Devittu, statement request, Mardi.` | `DEVITTO, STATEMENT REQUEST, MARDI.` (romanised) | `ಬ್ರಿಟು, ಱ್ಟೆ ಟೆಟುಟು, ಮರಡೀ.` (garbage; **dropped**, −0.825) |

What it shows:
- **Groq's detected `language` is unreliable.** It named the 5 Kannada clips English, Tamil, Hindi, Tamil and English; it never said Kannada unless pinned. The code therefore decides the call's language from the transcript's script (mostly Kannada letters means a Kannada call) and does not use that field.
- **The prompt decides the script.** With the English prompt and no pinned language, Kannada came back romanised or in Telugu script. Kannada words in the prompt keep it in Kannada script.
- **Pinning `kn` is not better.** It ties on pure-Kannada turns, wrecks the code-mixed turn, and could never hear an English caller. With `en,kn` the language is left to Whisper, the prompt is bilingual, and it switches to the Kannada prompt once the call is Kannada.
- **Accuracy is usable for intent, but not exact.** "EMI" became `ಎಮೇ` or `AMIAS`, and "ನನ್ನ" lost letters. Spoken digits come back as Kannada number words (ಒಂಬತ್ತು ಎಂಟು …), with 5 heard as `ಆಯದು` and the year garbled (`ಒಂಬಯನುರ ಎಂಬತ್ತಯಿದು`). The support prompt now lists the Kannada digit words, but **whether the agent verifies from this turn is untested** (see below).
- **Confidence filter:** every shipped-setting segment scored avg_logprob −0.14 to −0.49, so the −0.7 threshold kept them all, and no change was needed. It dropped one romanised turn under the English prompt (−0.701) and the pinned-`kn` garbage (−0.825). The values are in `backend/voice/tests/fixtures/kannada_stt_segments.json`.
- **Cost to English when `en,kn` is on:** 2 English clips (Indian voice). Pinned English with the domain prompt gave `My number is 987-6500002 and I was born on 3 November 1985` and `SR-40200`. Auto with the bilingual prompt gave `987650002` (**a digit lost**) and `born` misheard as `ban`, and `SR-40 to 00` (which `normalise_refs` repairs to `SR-40200`). This is 2 clips, so it's an indication only. Keep `VOICE_LANGUAGES=en` unless Kannada is being demoed.

**Not run:** the two scenarios through `eval.run_scenarios --audio --accent kn`. The team paused all Groq use for the live demo, so the agent's replies to these transcripts (intents, verification, the Kannada reply and voice) are covered only by offline unit tests with fakes. To run them when quota allows (about 6 speech-to-text and 20 LLM requests), start a voice service on a spare port with `VOICE_LANGUAGES=en,kn`, then run `python -m eval.run_scenarios --voice http://localhost:<port> --audio --accent kn --condition clean --only 13-kannada-repayment 14-kannada-statement`.

## Hindi (31 Oct 2026)

Task H2. The test set was 5 Hindi caller turns (pure Hindi, code-mixed, a mobile number, a date of birth, a reference), rendered with edge-tts `hi-IN-MadhurNeural`, clean, 16 kHz mono, and sent through the recorded-audio path (VAD trim, FLAC, `whisper-large-v3-turbo`, `verbose_json`, temperature 0) with the exact `language`/`prompt` a `CallLanguage` sends. Two of the turns are scenario lines (16 turn 1, 15 turn 3). There were 23 Groq speech-to-text requests in all (15 Hindi, 5 English, 3 diagnostics). **Caveat:** one synthetic male voice, 5 clips, no noise, no real speakers; a difference of one or two words is noise.

WER here is the word Levenshtein distance over the clip's reference text after lower-casing, `normalise_refs`, hyphens to spaces and punctuation removed. `98765 00002` is two reference words, so digits that come back with commas or hyphens between them count as many errors even when every digit is present: read the transcript, not only the number.

| Turn (said) | (a) Auto + multilingual prompt (**shipped for `en,kn,hi`, before the call is Hindi**) | (b) Auto + Hindi prompt (what the app sends once the call is Hindi) | (c) Pinned `hi` + Hindi prompt |
|---|---|---|---|
| मुझे मेरा लोन स्टेटमेंट चाहिए | `मुझे मेरा लोन, स्टेटमेंट, चाहिए.` (0/5) | `मुझे मेरा लोन स्टेटमेंट चाहिए।` (0/5) | same as (b) |
| मेरी अगली EMI कितनी है, और कब भरनी है? | `मेरी अगली EMI कितनी है, और कब भरनी है?` (0/9) | `मेरी अगली EMI कितनी है और कब भरनी है।` (0/9) | same as (b) |
| मेरा मोबाइल नंबर 98765 00002 है। | `मेरा मोबाइल नंबर 9, 5, 00, 00, 00, 00 है.` (**digits lost**, 6/6) | `मेरा मोबाइल नमबर 9, आजे 5, 00, 00, 00, 00 है।` (**digits lost**, 8/6) | same as (b) |
| मेरी जन्म तिथि 3 नवंबर 1985 है। | `मेरी जन्मति थी 3 नवंबर 1985 है.` (2/7: `जन्म तिथि` split wrongly, date right) | `मेरी जन्मति थी 3 नवंबर 1980 है।` (3/7, **year wrong**) | same as (b) |
| SR-40200 का स्टेटस क्या है? | `SR-402.00 का स्टेटस क्या है?` (0/6 after `normalise_refs` → `SR-40200`) | `इस आर्क 4-02-00 का स्टेटस क्या है।` (5/6: "SR" **transliterated**, not repairable) | same as (b) |
| **Total (33 reference words)** | **8 errors, 24% WER** | 16 errors, 48% WER | 16 errors, 48% WER |

Script and detected language, per configuration:

| | (a) Auto + multilingual | (b) Auto + Hindi prompt | (c) Pinned `hi` |
|---|---|---|---|
| Script of the 5 outputs | Devanagari ×5 (English terms EMI, SR kept Latin) | Devanagari ×5 ("SR" written in Devanagari) | Devanagari ×5 |
| Groq's detected `language` | Hindi ×5 | Hindi ×5 | Hindi ×5 (pinned) |
| Urdu or Latin script for Hindi words | 0 of 5 | 0 of 5 | 0 of 5 |
| Segments dropped by the confidence filter | 0 (avg_logprob −0.10 to −0.24) | 0 (−0.08 to −0.26) | 0 (−0.08 to −0.26) |
| Latency per request | 0.34–0.48 s | 0.31–0.58 s | 0.32–0.36 s |

What it shows:
- **Hindi is in far better shape than Kannada was.** Unlike Kannada, Groq's detected language was right on every clip, and no configuration wrote Hindi in Urdu or Latin script, so the script-based call-language switch works on the first Hindi turn. Pure and code-mixed sentences came back exact in every configuration, and "EMI" stayed Latin.
- **(b) and (c) are byte-identical** on all 5 clips: once the prompt is the Hindi one, Whisper's own detection and a pinned `hi` make no difference. Pinning gains nothing and could never hear an English or Kannada caller.
- **The multilingual prompt did better than the Hindi prompt** on the two turns that carry data: it kept the year (1985, not 1980) and wrote the reference in Latin (`SR-402.00`, which `normalise_refs` repairs) where the Hindi prompt transliterated "SR" into Devanagari. Both are single-clip observations. A diagnostic request with `Bank customer call.` prefixed to the Hindi prompt still gave `इस आर्क 4-02-00`, so an English header alone does not fix the transliteration; `HINDI_PROMPT` is left as H1 shipped it.
- **Digit strings are the weak point, in every configuration.** `98765 00002` became `9, 5, 00, 00, 00, 00` (five digits gone). Two diagnostics under (a): the scenario's full identity turn (`मेरा मोबाइल नंबर 98765 00002, जन्म तिथि 3 नवंबर 1985.`) came back as `9-8-7-6-5-00-00-2, जन्म तिथी 3 नवंबर 1980` (all ten digits present in order, year wrong); the number spoken digit by digit (`9 8 7 6 5 0 0 0 0 2`) came back as `987650002` (**one zero lost**, the same loss the Kannada section saw on the English identity clip). So turn 2 of scenarios 15 and 16 (verification) is the turn most likely to fail over audio, and the fix would be in how the agent re-asks for digits, not in the prompt.
- **Confidence filter:** every segment in every configuration scored avg_logprob between −0.08 and −0.29, well inside the −0.7 threshold; nothing was dropped and nothing needed changing.
- **Cost to English when `en,kn,hi` is on:** 5 English clips (Indian voice), auto with the multilingual prompt. `Can you check the status of SR-40200?`, `When is my next EMI due?` and `I need a copy of my loan statement.` were exact; `My number is 98765 00002 and I was born on 3 November 1985.` came back as `My number is 98765-00002 and I was born on 3rd November, 1985.` (every digit kept, `3rd` the only word error: 1/13), **better than the `en,kn` bilingual prompt did on the same clip** (a digit lost). The romanised code-mix `EMI kab hai for my vehicle loan?` came back as `EMI कब है for my vehicle loan?` (2/7): the Hindi words were written in Devanagari, which is a transcript difference rather than a hearing error; at 17% Devanagari letters it stays under `CODE_MIX_SHARE`, so the call stays English. All 5 were detected as English. Total 3 errors in 42 words (7%), of which 2 are the script choice. 5 clips, so an indication only.

**Decision (Step 3):** `MULTILINGUAL_PROMPT` is unchanged. The trigger for reordering it (configuration (a) writing Hindi in Urdu or Latin script more often than (b)) did not fire: 0 of 5 in both. Its `en,kn` form therefore stays byte-identical to `BILINGUAL_PROMPT`.

**Not run:** scenarios 15 and 16 through `eval.run_scenarios --audio --accent hi` (no services were started for this task). To run them when a voice service is up with `VOICE_LANGUAGES=en,kn,hi` (about 6 speech-to-text and 20 LLM requests): `cd backend/voice && .venv/bin/python -m eval.audio.render --source scenarios --accents hi --conditions clean` once, then `.venv/bin/python -m eval.run_scenarios --voice http://localhost:<port> --audio --accent hi --condition clean --only 15-hindi-repayment 16-hindi-statement`, and paste the result here.
