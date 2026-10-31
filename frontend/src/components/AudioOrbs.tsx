import { useEffect, useRef, useState } from 'react';

type Speaker = 'none' | 'customer' | 'agent';

const SPEAKING = 0.06; // RMS above this counts as speech (0..1)

/** Live level of an audio stream, written to a CSS variable on `target` every frame (no React re-render per frame). */
function useLevel(stream: MediaStream | null, target: React.RefObject<HTMLElement>, onSpeaking: (on: boolean) => void) {
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
    let was = false;
    const tick = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const v of data) sum += ((v - 128) / 128) ** 2;
      const rms = Math.sqrt(sum / data.length);
      smooth = smooth * 0.7 + rms * 0.3;
      target.current?.style.setProperty('--level', Math.min(1, smooth * 6).toFixed(3));
      const now = smooth > SPEAKING;
      if (now !== was) {
        was = now;
        speakingRef.current(now);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      void ctx.close().catch(() => undefined);
      target.current?.style.setProperty('--level', '0');
    };
  }, [stream, target]);
}

/**
 * Two orbs that move with the live audio: the caller's microphone and the agent's voice. While a call is live, the
 * screen shows who is talking instead of sitting still between transcript updates.
 */
export function AudioOrbs({ live, agentAudio }: { live: boolean; agentAudio: React.RefObject<HTMLAudioElement> }) {
  const [mic, setMic] = useState<MediaStream | null>(null);
  const [agentStream, setAgentStream] = useState<MediaStream | null>(null);
  const [customerOn, setCustomerOn] = useState(false);
  const [agentOn, setAgentOn] = useState(false);
  const youRef = useRef<HTMLDivElement>(null);
  const agentRef = useRef<HTMLDivElement>(null);

  // a read-only copy of the microphone, for the level meter only (the call has its own capture)
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
      setCustomerOn(false);
    };
  }, [live]);

  // the agent's voice arrives as the <audio> element's stream once WebRTC connects
  useEffect(() => {
    if (!live) {
      setAgentStream(null);
      setAgentOn(false);
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

  useLevel(mic, youRef, setCustomerOn);
  useLevel(agentStream, agentRef, setAgentOn);

  const speaker: Speaker = customerOn ? 'customer' : agentOn ? 'agent' : 'none';
  const status = !live ? 'Microphone off' : speaker === 'customer' ? 'You’re speaking' : speaker === 'agent' ? 'Agent speaking' : 'Listening…';

  return (
    <div className={`orbs${live ? ' live' : ''}`} data-speaker={speaker}>
      <div className="orb-col">
        <div ref={youRef} className={`orb you${customerOn ? ' on' : ''}`} aria-hidden="true">
          <span className="orb-core" />
        </div>
        <span className="orb-label">You</span>
      </div>
      <div className="orb-col">
        <div ref={agentRef} className={`orb agent${agentOn ? ' on' : ''}`} aria-hidden="true">
          <span className="orb-core" />
        </div>
        <span className="orb-label">Agent</span>
      </div>
      <p className="orb-status" role="status" aria-live="polite">
        {status}
      </p>
    </div>
  );
}
