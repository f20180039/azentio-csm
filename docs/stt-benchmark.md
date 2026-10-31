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
