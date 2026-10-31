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
