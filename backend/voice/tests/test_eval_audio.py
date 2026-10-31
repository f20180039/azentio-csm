import json
import math
import struct
import wave

from eval.audio.noise import mix_at_snr, read_mono, render_noisy, rms, write_mono
from eval.audio.render import load_inputs, manifest_rows


def _sine(count, frequency=440, rate=16000, amplitude=0.2):
    return [amplitude * math.sin(2 * math.pi * frequency * i / rate) for i in range(count)]


def test_mixer_hits_five_db_snr():
    speech = _sine(16000)
    noise = _sine(16000, frequency=173, amplitude=0.1)
    mixed = mix_at_snr(speech, noise, 5.0)
    noise_component = [actual - wanted for actual, wanted in zip(mixed, speech)]
    measured = 20 * math.log10(rms(speech) / rms(noise_component))
    assert abs(measured - 5.0) <= 0.5


def test_noisy_wave_is_16khz_mono_and_has_room_tone_padding(tmp_path):
    source, output = tmp_path / "speech.wav", tmp_path / "noisy.wav"
    write_mono(source, 16000, _sine(8000))
    render_noisy(source, output, [_sine(3000), _sine(2500, 510), _sine(4000, 610)], seed=27)
    with wave.open(str(output), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == 8000 + 2 * round(16000 * 0.7)
    rate, samples = read_mono(output)
    assert rate == 16000 and len(samples) > 8000


def test_utterance_manifest_rows_match_csv_inputs(tmp_path):
    inputs = load_inputs("utterances")
    manifest = manifest_rows(inputs[:1], "utterances", ["in"], ["clean"], tmp_path)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert len(inputs) == 60
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [(r["text"], r["intents"], r["file"]) for r in saved] == [
        (inputs[0]["text"], inputs[0]["intents"], "utterances/in/clean/U001.wav")]

