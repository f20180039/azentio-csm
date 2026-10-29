"""Headless WebRTC caller: starts a renewal call, plays synthesised customer speech as the mic, times each reply.

Needs the renewals API and the voice service running.
  .venv/bin/python scripts/headless_call.py [--policy HF-2291-0457] [--voice-url http://localhost:7861]
Prints per-turn latency (end of customer speech -> first agent audio) and the call's audit event types.
"""

import argparse
import asyncio
import fractions
import io
import statistics
import time

import av
import edge_tts
import httpx
import numpy as np
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription

RATE, FRAME = 48000, 960  # 20 ms frames
LOUD = 300  # RMS above this counts as agent speech
CUSTOMER_LINES = ["yes speaking", "fourteenth March nineteen eighty", "can you give me a discount"]


async def speech(text: str) -> np.ndarray:
    mp3 = bytearray()
    async for c in edge_tts.Communicate(text, "en-IN-PrabhatNeural").stream():
        if c["type"] == "audio":
            mp3.extend(c["data"])
    out = []
    with av.open(io.BytesIO(bytes(mp3)), format="mp3") as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
        for f in container.decode(audio=0):
            for r in resampler.resample(f):
                out.append(r.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.int16)


class Mic(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self.queue = np.zeros(0, dtype=np.int16)
        self.pts = 0
        self.start: float | None = None
        self.speaking_until = 0.0

    def say(self, pcm: np.ndarray) -> None:
        self.queue = np.concatenate([self.queue, pcm])
        self.speaking_until = time.perf_counter() + len(self.queue) / RATE

    async def recv(self):
        if self.start is None:
            self.start = time.perf_counter()
        await asyncio.sleep(max(0, self.start + self.pts / RATE - time.perf_counter()))
        chunk, self.queue = self.queue[:FRAME], self.queue[FRAME:]
        if len(chunk) < FRAME:
            chunk = np.concatenate([chunk, np.zeros(FRAME - len(chunk), dtype=np.int16)])
        frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate, frame.pts, frame.time_base = RATE, self.pts, fractions.Fraction(1, RATE)
        self.pts += FRAME
        return frame


async def main(args) -> None:
    async with httpx.AsyncClient(base_url=args.api, auth=("analyst", "analyst"), timeout=10) as api:
        started = (await api.post("/renewals/calls", json={"policyId": args.policy})).raise_for_status().json()
    call_id, case_id = started["callId"], started["caseId"]
    print(f"call {call_id} case {case_id}")

    lines = [await speech(t) for t in CUSTOMER_LINES]
    mic = Mic()
    pc = RTCPeerConnection()
    pc.addTrack(mic)
    heard: list[tuple[float, float]] = []

    @pc.on("track")
    def on_track(track):
        async def listen():
            while True:
                try:
                    f = await track.recv()
                except Exception:
                    return
                a = f.to_ndarray().astype(np.float32)
                heard.append((time.perf_counter(), float(np.sqrt((a**2).mean()))))

        asyncio.ensure_future(listen())

    await pc.setLocalDescription(await pc.createOffer())
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            f"{args.voice_url}/api/offer",
            json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "requestData": {"callId": call_id}},
        )
        answer = resp.raise_for_status().json()
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
    t_connected = time.perf_counter()

    def first_loud_after(t: float) -> float | None:
        return next((at for at, rms in heard if at >= t and rms > LOUD), None)

    async def wait_quiet(limit: float) -> None:
        while time.perf_counter() < limit:
            await asyncio.sleep(0.2)
            recent = [rms for at, rms in heard if at > time.perf_counter() - 1.5]
            if recent and max(recent) < LOUD and first_loud_after(time.perf_counter() - 30):
                return

    async def wait_reply(since: float, limit: float = 25) -> float | None:
        while time.perf_counter() < since + limit:
            await asyncio.sleep(0.02)
            at = first_loud_after(since)
            if at:
                return at
        return None

    greeting_at = await wait_reply(t_connected)
    print(f"greeting heard {((greeting_at or 0) - t_connected) * 1000:.0f} ms after connect" if greeting_at else "greeting NEVER heard")
    await wait_quiet(time.perf_counter() + 30)

    rows = []
    for text, pcm in zip(CUSTOMER_LINES, lines):
        await asyncio.sleep(args.pause)
        mic.say(pcm)
        end = mic.speaking_until
        at = await wait_reply(end)
        ms = round((at - end) * 1000) if at else None
        rows.append((text, ms))
        print(f"{'NEVER' if ms is None else f'{ms} ms':>8} | {text}")
        if at:
            await wait_quiet(time.perf_counter() + 40)

    await asyncio.sleep(2)
    await pc.close()
    await asyncio.sleep(3)  # let the voice service record the end of the call

    async with httpx.AsyncClient(base_url=args.api, auth=("analyst", "analyst"), timeout=10) as api:
        audit = (await api.get(f"/cases/{case_id}/audit")).raise_for_status().json()
    events = [e.get("eventType") or e.get("type") or e.get("action") for e in audit]
    print("audit:", ", ".join(str(e) for e in events))

    timed = [ms for _, ms in rows if ms is not None]
    print("\n| Customer says | First agent audio after speech ends |\n|---|---|")
    for text, ms in rows:
        print(f"| {text} | {'no reply' if ms is None else f'{ms} ms'} |")
    if timed:
        print(f"| **median** | **{statistics.median(timed):.0f} ms** |")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8080/api/v1")
    p.add_argument("--voice-url", default="http://localhost:7861")
    p.add_argument("--policy", default="HF-2291-0457")
    p.add_argument("--pause", type=float, default=3.0, help="seconds between turns (Groq free-tier pacing)")
    asyncio.run(main(p.parse_args()))
