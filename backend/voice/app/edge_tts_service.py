import av
import edge_tts
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

from .speech import CallLanguage, voice_for

SAMPLE_RATE = 24000


class EdgeTTSService(TTSService):
    """edge-tts streams MP3; decode it to 24 kHz PCM as it arrives so playback starts on the first chunk."""

    def __init__(self, voice: str, call_language: CallLanguage | None = None, **kwargs):
        super().__init__(
            push_start_frame=True,
            push_stop_frames=True,
            settings=TTSSettings(model=None, voice=voice, language=None),
            **kwargs,
        )
        self._voice = voice
        self._call_language = call_language

    def voice_for(self, text: str) -> str:
        return voice_for(text, self._voice, self._call_language)

    async def run_tts(self, text: str, context_id: str):
        voice = self.voice_for(text)

        async def pcm():
            codec = av.CodecContext.create("mp3", "r")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)

            def decode(data: bytes):
                for packet in codec.parse(data):
                    for frame in codec.decode(packet):
                        for r in resampler.resample(frame):
                            yield bytes(r.planes[0])[: r.samples * 2]

            async for chunk in edge_tts.Communicate(text, voice).stream():
                if chunk["type"] == "audio":
                    for pcm_bytes in decode(chunk["data"]):
                        yield pcm_bytes
            for pcm_bytes in decode(b""):
                yield pcm_bytes

        async for frame in self._stream_audio_frames_from_iterator(
            pcm(), in_sample_rate=SAMPLE_RATE, context_id=context_id
        ):
            yield frame
