import { useEffect, useRef, useState } from 'react';

const SPEAKING = 0.06; // RMS above this counts as speech (0..1)
const HOLD_MS = 450; // keep "speaking" briefly through the gaps between words, so the bubble does not flicker

/** Writes a stream's live level (0..1) to a CSS variable on `target` each frame, and reports speech on/off. */
function useLevel(stream: MediaStream | null, target: React.RefObject<HTMLElement>, prop: string, onSpeaking: (on: boolean) => void) {
  const speakingRef = useRef(onSpeaking);
  speakingRef.current = onSpeaking;
  useEffect(() => {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!stream || !Ctx || stream.getAudioTracks().length === 0) return;
    const ctx = new Ctx();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.6;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    let frame = 0;
    let smooth = 0;
    let lastLoud = 0;
    let on = false;
    const tick = (now: number) => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const v of data) sum += ((v - 128) / 128) ** 2;
      smooth = smooth * 0.7 + Math.sqrt(sum / data.length) * 0.3;
      target.current?.style.setProperty(prop, Math.min(1, smooth * 6).toFixed(3));
      if (smooth > SPEAKING) lastLoud = now;
      const speaking = now - lastLoud < HOLD_MS;
      if (speaking !== on) {
        on = speaking;
        speakingRef.current(on);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      void ctx.close().catch(() => undefined);
      target.current?.style.setProperty(prop, '0');
      speakingRef.current(false);
    };
  }, [stream, target, prop]);
}

/**
 * Who is talking right now on a live mic call. Meters a read-only copy of the microphone and the agent's voice
 * (the `<audio>` element WebRTC plays into), writing `--you-level` and `--agent-level` onto `levelTarget`.
 */
export function useLiveSpeech(live: boolean, agentAudio: React.RefObject<HTMLAudioElement>, levelTarget: React.RefObject<HTMLElement>) {
  const [mic, setMic] = useState<MediaStream | null>(null);
  const [agentStream, setAgentStream] = useState<MediaStream | null>(null);
  const [customer, setCustomer] = useState(false);
  const [agent, setAgent] = useState(false);

  useEffect(() => {
    if (!live || !navigator.mediaDevices?.getUserMedia) return;
    let stream: MediaStream | null = null;
    let cancelled = false;
    navigator.mediaDevices
      .getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      .then((s) => {
        if (cancelled) s.getTracks().forEach((t) => t.stop());
        else setMic((stream = s));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
      setMic(null);
    };
  }, [live]);

  useEffect(() => {
    if (!live) {
      setAgentStream(null);
      return;
    }
    const poll = window.setInterval(() => {
      const src = agentAudio.current?.srcObject;
      if (src instanceof MediaStream && src.getAudioTracks().length) {
        setAgentStream(src);
        window.clearInterval(poll);
      }
    }, 300);
    return () => window.clearInterval(poll);
  }, [live, agentAudio]);

  useLevel(mic, levelTarget, '--you-level', setCustomer);
  useLevel(agentStream, levelTarget, '--agent-level', setAgent);
  return { customer: live && customer, agent: live && agent && !customer };
}

/** A "typing…"-style bubble in the conversation while someone is speaking; its dots move with the live level. */
export function SpeakingBubble({ who }: { who: 'customer' | 'agent' }) {
  return (
    <li className={`sc-turn ${who} sc-speaking`} aria-label={who === 'customer' ? 'Customer is speaking' : 'Agent is speaking'}>
      <span className="sc-dots" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    </li>
  );
}

export function speechStatus(live: boolean, s: { customer: boolean; agent: boolean }): string {
  if (!live) return 'Microphone off';
  return s.customer ? 'You’re speaking' : s.agent ? 'Agent speaking' : 'Listening…';
}
