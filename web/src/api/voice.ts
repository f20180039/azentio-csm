import { VOICE_BASE } from './renewals';

export interface VoiceHandlers {
  onUserText: (text: string) => void;
  onBotText: (text: string) => void;
  onDisconnected: () => void;
  onError: (message: string) => void;
}

export interface VoiceSession {
  disconnect: () => Promise<void>;
}

/**
 * Connects the browser mic and speaker to the voice service over Pipecat SmallWebRTC.
 * The libraries load on demand so the queue page and the typed-call path never pull in WebRTC code.
 * requestData carries only the call id; the voice service reads everything else from the API.
 */
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
  await client.connect({ webrtcRequestParams: { endpoint: `${VOICE_BASE}/api/offer`, requestData: { callId } } });
  return { disconnect: () => client.disconnect() };
}
