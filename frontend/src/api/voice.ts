import { VoicePath } from './paths/voice';
import { VOICE_BASE } from './renewals';

export interface VoiceHandlers {
  onUserText: (text: string) => void;
  onBotText: (text: string) => void;
  onDisconnected: () => void;
  onError: (message: string) => void;
}

export interface VoiceSession {
  disconnect: () => Promise<void>;
  /** Mutes or unmutes the microphone track; the connection and the agent's audio stay up. */
  setMicEnabled?: (on: boolean) => void;
}

/**
 * Connects the browser mic and speaker to the voice service over Pipecat SmallWebRTC.
 * The libraries load on demand so the queue page and the typed-call path never pull in WebRTC code.
 * requestData carries only the call id; the voice service reads everything else from the API.
 */
/** Turns whatever the transport rejects with (a Response, a TypeError, an Error) into a message for the operator. */
export function describeVoiceError(e: unknown): string {
  const seen = new Set<unknown>();
  let cur: unknown = e;
  while (cur && typeof cur === 'object' && !seen.has(cur)) {
    seen.add(cur);
    const o = cur as { status?: number; message?: string; cause?: unknown };
    if (o.status === 409 || (typeof o.message === 'string' && o.message.includes('CALL_IN_PROGRESS'))) {
      return 'This call is already live in another tab or window.';
    }
    if (cur instanceof TypeError || (typeof o.message === 'string' && /failed to fetch|networkerror|load failed/i.test(o.message))) {
      return `Voice service unreachable at ${VOICE_BASE}. Use 'Type instead' to continue.`;
    }
    cur = o.cause;
  }
  return e instanceof Error && e.message ? e.message : 'Check the voice service and microphone permission.';
}

export async function connectVoice(callId: string, audio: HTMLAudioElement | null, h: VoiceHandlers): Promise<VoiceSession> {
  const [{ PipecatClient }, { SmallWebRTCTransport }] = await Promise.all([
    import('@pipecat-ai/client-js'),
    import('@pipecat-ai/small-webrtc-transport'),
  ]);
  const client = new PipecatClient({
    transport: new SmallWebRTCTransport({ waitForICEGathering: true }),
    enableMic: true,
    enableCam: false,
    callbacks: {
      onUserTranscript: (d) => {
        if (d.final && d.text.trim()) h.onUserText(d.text.trim());
      },
      onBotOutput: (d) => {
        if (d.aggregated_by === 'word' || d.will_be_spoken === false) return;
        if (d.text.trim()) h.onBotText(d.text.trim());
      },
      onTrackStarted: (track, participant) => {
        if (track.kind === 'audio' && !participant?.local && audio) {
          audio.srcObject = new MediaStream([track]);
          void audio.play().catch(() => undefined);
        }
      },
      onDisconnected: h.onDisconnected,
      onError: (m) => h.onError(typeof m?.data === 'string' ? m.data : 'The voice connection reported an error.'),
    },
  });
  try {
    await client.connect({ webrtcRequestParams: { endpoint: `${VOICE_BASE}${VoicePath.RENEWAL_OFFER}`, requestData: { callId } } });
  } catch (e) {
    void client.disconnect().catch(() => undefined);
    throw new Error(describeVoiceError(e));
  }
  return { disconnect: () => client.disconnect() };
}
