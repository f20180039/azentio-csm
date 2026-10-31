import { ApiError, toApiError } from './errors';
import { get, MOCK_MODE, postJson } from './client';
import { VOICE_BASE } from './renewals';
import { describeVoiceError, type VoiceSession } from './voice';
import { mockSupport } from './mockSupport';
import { CoreApiPath } from './paths/core';
import { SimulatorPath } from './paths/simulator';
import { VoicePath } from './paths/voice';
import {
  Intent,
  IntentSource,
  LegacyIntent,
  RecordKind,
  SupportChannel,
  SupportOutcome,
  TurnRole,
  Verification,
} from '../vocab';

export { RecordKind, SupportChannel, SupportOutcome, Verification };

export const SIMULATOR_BASE: string =
  (import.meta.env.VITE_SIMULATOR_BASE as string | undefined) ?? 'http://localhost:8090/v1';

/* ---------- shared contract types (docs/superpowers/plans/2026-10-31-csm-voice-agent.md) ---------- */

export const SUPPORT_OUTCOMES: SupportOutcome[] = Object.values(SupportOutcome);

export interface ToolTrace {
  name: string;
  args: Record<string, unknown>;
  result_summary?: string | null;
}

export interface TurnMeta {
  intents?: string[];
  intent_source?: IntentSource;
  verified?: boolean;
  verify_failures?: number;
  locked?: boolean;
  no_speech?: boolean;
  tool_trace?: ToolTrace[];
  retrieved?: Record<string, unknown>;
  refs?: string[];
  [key: string]: unknown;
}

export interface SupportTurn {
  seq: number;
  role: TurnRole;
  text: string;
  at: string;
  meta: TurnMeta;
}

export interface SupportCall {
  id: string;
  channel: SupportChannel;
  startedAt: string;
  endedAt: string | null;
  outcome: SupportOutcome | null;
  verified: boolean;
  turns: SupportTurn[];
}

export interface SupportCallSummary {
  id: string;
  channel: SupportChannel;
  startedAt: string;
  endedAt: string | null;
  outcome: SupportOutcome | null;
  verified: boolean;
  turnCount: number;
  intents: string[];
}

export interface SimTurn {
  file: string;
  transcript: string;
  no_speech: boolean;
  intents: string[];
  verified: boolean;
  tool_trace: ToolTrace[];
  retrieved: Record<string, unknown>;
  reply_text: string | null;
  reply_audio_b64: string | null;
}

export interface SimAudioResult {
  call_id: string;
  turns: SimTurn[];
}

export interface OfferBody {
  sdp: string;
  type: string;
  pc_id?: string | null;
  restart_pc?: boolean;
  requestData?: Record<string, unknown>;
}

export interface OfferAnswer {
  sdp: string;
  type: string;
  pc_id: string;
  call_id: string;
}

export interface OpsRecord {
  ref: string;
  kind: RecordKind;
  category: string | null;
  status: string | null;
  summary: string;
  customer_ref: string | null;
  call_id: string | null;
  created_at: string;
  escalated: boolean | null;
}

/* ---------- Spring: call records ---------- */

function normaliseCall(c: SupportCall): SupportCall {
  return {
    ...c,
    endedAt: c.endedAt ?? null,
    outcome: c.outcome ?? null,
    turns: (Array.isArray(c.turns) ? c.turns : []).map((t) => ({ ...t, meta: t.meta ?? {} })),
  };
}

const liveSupport = {
  startCall(channel: SupportChannel = SupportChannel.VOICE): Promise<{ id: string }> {
    return postJson(CoreApiPath.SUPPORT_CALLS, { channel });
  },

  async getCall(id: string): Promise<SupportCall> {
    return normaliseCall(await get<SupportCall>(CoreApiPath.supportCall(id)));
  },

  async listCalls(outcome?: SupportOutcome): Promise<SupportCallSummary[]> {
    const params = new URLSearchParams({ limit: '50' });
    if (outcome) params.set('outcome', outcome);
    const r = await get<{ items?: SupportCallSummary[] }>(`${CoreApiPath.SUPPORT_CALLS}?${params}`);
    return (r?.items ?? []).map((c) => ({ ...c, intents: c.intents ?? [] }));
  },

  endCall(id: string, outcome: SupportOutcome): Promise<unknown> {
    return postJson(CoreApiPath.supportCallEnd(id), { outcome });
  },

  /* ---------- voice service ---------- */

  async simAudio(files: File[], callId?: string): Promise<SimAudioResult> {
    const form = new FormData();
    files.forEach((f) => form.append('files', f, f.name));
    if (callId) form.append('call_id', callId);
    const res = await reach('voice service', VOICE_BASE, () => fetch(`${VOICE_BASE}${VoicePath.SIM_AUDIO}`, { method: 'POST', body: form }));
    return (await res.json()) as SimAudioResult;
  },

  async supportOffer(body: OfferBody, fetchImpl: typeof fetch = fetch): Promise<OfferAnswer> {
    const res = await reach('voice service', VOICE_BASE, () =>
      fetchImpl(`${VOICE_BASE}${VoicePath.SUPPORT_OFFER}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }),
    );
    return (await res.json()) as OfferAnswer;
  },

  /* ---------- bank simulator ---------- */

  async listRecords(kind: RecordKind): Promise<OpsRecord[]> {
    const res = await reach('bank simulator', SIMULATOR_BASE, () =>
      fetch(`${SIMULATOR_BASE}${SimulatorPath.OPS_RECORDS}?kind=${kind}`, {
        headers: { Accept: 'application/json', Authorization: 'Basic ' + btoa('ops:ops') },
      }),
    );
    return ((await res.json()) as { items?: OpsRecord[] }).items ?? [];
  },

  connectSupportVoice: liveConnectSupportVoice,
};

async function reach(what: string, base: string, call: () => Promise<Response>): Promise<Response> {
  let res: Response;
  try {
    res = await call();
  } catch {
    throw new ApiError({ status: 0, title: `Cannot reach the ${what}`, detail: `Check that it is running at ${base}.` });
  }
  if (!res.ok) {
    const err = await toApiError(res);
    throw new ApiError({ status: err.status, title: `The ${what} refused the request`, detail: err.detail ?? err.title });
  }
  return res;
}

/* ---------- microphone: Pipecat SmallWebRTC against /support/offer ---------- */

export interface SupportVoiceHandlers {
  onCallId: (callId: string) => void;
  onDisconnected: () => void;
  onError: (message: string) => void;
}

/**
 * Same transport as the renewals call (api/voice.ts). The offer goes through supportOffer, so the
 * call_id the voice service creates comes back to the page; transcripts and meta arrive by polling Spring.
 */
async function liveConnectSupportVoice(
  callId: string | undefined,
  audio: HTMLAudioElement | null,
  h: SupportVoiceHandlers,
): Promise<VoiceSession> {
  const [{ PipecatClient }, { SmallWebRTCTransport }] = await Promise.all([
    import('@pipecat-ai/client-js'),
    import('@pipecat-ai/small-webrtc-transport'),
  ]);
  const client = new PipecatClient({
    transport: new SmallWebRTCTransport({ waitForICEGathering: true }),
    enableMic: true,
    enableCam: false,
    callbacks: {
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
  const endpoint = `${VOICE_BASE}${VoicePath.SUPPORT_OFFER}`;
  const nativeFetch = window.fetch;
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : null;
    const url = req ? req.url : String(input);
    if (url !== endpoint) return nativeFetch(input, init);
    const raw = req ? await req.text() : String(init?.body ?? '{}');
    const answer = await api.supportOffer(JSON.parse(raw) as OfferBody, nativeFetch);
    if (answer.call_id) h.onCallId(answer.call_id);
    return new Response(JSON.stringify(answer), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  try {
    await client.connect({
      webrtcRequestParams: { endpoint, ...(callId ? { requestData: { call_id: callId } } : {}) },
    });
  } catch (e) {
    void client.disconnect().catch(() => undefined);
    throw new Error(describeVoiceError(e));
  } finally {
    window.fetch = nativeFetch;
  }
  return { disconnect: () => client.disconnect() };
}

export type SupportApi = typeof liveSupport;

const api: SupportApi = MOCK_MODE ? (mockSupport as SupportApi) : liveSupport;

export const startCall = (channel?: SupportChannel) => api.startCall(channel);
export const getCall = (id: string) => api.getCall(id);
export const listCalls = (outcome?: SupportOutcome) => api.listCalls(outcome);
export const endCall = (id: string, outcome: SupportOutcome) => api.endCall(id, outcome);
export const simAudio = (files: File[], callId?: string) => api.simAudio(files, callId);
export const supportOffer = (body: OfferBody) => api.supportOffer(body);
export const listRecords = (kind: RecordKind) => api.listRecords(kind);
export const connectSupportVoice = (callId: string | undefined, audio: HTMLAudioElement | null, h: SupportVoiceHandlers) =>
  api.connectSupportVoice(callId, audio, h);

/* ---------- presentation helpers shared by the desk and the call view ---------- */

const INTENT_LABEL: Record<Intent | LegacyIntent, string> = {
  [Intent.LOAN_APPLICATION]: 'Loan application',
  [Intent.REPAYMENT]: 'Repayment',
  [Intent.ACCOUNT]: 'Account',
  [Intent.SERVICE_REQUEST]: 'Service request',
  [Intent.PRODUCT_INFO]: 'Product question',
  [Intent.COMPLAINT]: 'Complaint',
  [Intent.INSURANCE]: 'Insurance',
  [Intent.IDENTITY]: 'Identity',
  [Intent.HUMAN_AGENT]: 'Human agent',
  [Intent.UNSUPPORTED]: 'Unsupported',
  [Intent.UNCLEAR]: 'Unclear',
  [Intent.CHITCHAT]: 'Chitchat',
  [LegacyIntent.TRANSACTION]: 'Transaction',
  [LegacyIntent.SERVICE_REQUEST_STATUS]: 'Service request status',
  [LegacyIntent.PRODUCT_QUESTION]: 'Product question',
  [LegacyIntent.FAQ]: 'Product question',
  [LegacyIntent.STATEMENT]: 'Statement',
  [LegacyIntent.ESCALATION]: 'Escalation',
  [LegacyIntent.GREETING]: 'Greeting',
};

export function intentLabel(intent: string): string {
  const key = intent.toUpperCase();
  return INTENT_LABEL[key as Intent | LegacyIntent] ?? key.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export function intentTone(intent: string): string {
  const key = intent.toUpperCase();
  if (key === Intent.UNSUPPORTED) return 'warn';
  if (key === Intent.UNCLEAR) return 'dim';
  if (key === Intent.COMPLAINT || key === LegacyIntent.ESCALATION) return 'bad';
  return 'neutral';
}

export const OUTCOME_LABEL: Record<SupportOutcome, string> = {
  [SupportOutcome.RESOLVED]: 'Resolved',
  [SupportOutcome.TICKET_CREATED]: 'Ticket created',
  [SupportOutcome.COMPLAINT_REGISTERED]: 'Complaint registered',
  [SupportOutcome.ROUTED]: 'Routed',
  [SupportOutcome.ESCALATED]: 'Escalated',
  [SupportOutcome.ABANDONED]: 'Abandoned',
};

export const OUTCOME_TONE: Record<SupportOutcome, string> = {
  [SupportOutcome.RESOLVED]: 'ok',
  [SupportOutcome.TICKET_CREATED]: 'info',
  [SupportOutcome.COMPLAINT_REGISTERED]: 'warn',
  [SupportOutcome.ROUTED]: 'warn',
  [SupportOutcome.ESCALATED]: 'bad',
  [SupportOutcome.ABANDONED]: 'dim',
};

export const CHANNEL_LABEL: Record<SupportChannel, string> = {
  [SupportChannel.VOICE]: 'Microphone',
  [SupportChannel.SIM_AUDIO]: 'Audio files',
  [SupportChannel.TEXT]: 'Text',
};

/** From the latest customer turn's meta; the call-level flag covers calls whose turns carry no meta yet. */
export function verificationOf(call: Pick<SupportCall, 'turns' | 'verified'>): { state: Verification; failures: number } {
  const last = [...call.turns].reverse().find((t) => t.role === TurnRole.CUSTOMER && (t.meta.verified !== undefined || t.meta.locked !== undefined));
  const failures = last?.meta.verify_failures ?? 0;
  if (last?.meta.locked) return { state: Verification.LOCKED, failures };
  if (last?.meta.verified || call.verified) return { state: Verification.VERIFIED, failures };
  return { state: Verification.NOT_VERIFIED, failures };
}

/** The outcome an operator most likely wants, from the references the agent created. */
export function suggestOutcome(call: Pick<SupportCall, 'turns'>): SupportOutcome {
  const refs = call.turns.flatMap((t) => t.meta.refs ?? []);
  if (refs.some((r) => r.startsWith('ESC-'))) return SupportOutcome.ESCALATED;
  if (refs.some((r) => r.startsWith('CMP-'))) return SupportOutcome.COMPLAINT_REGISTERED;
  if (refs.some((r) => r.startsWith('SR-'))) return SupportOutcome.TICKET_CREATED;
  if (refs.some((r) => r.startsWith('RQ-'))) return SupportOutcome.ROUTED;
  return call.turns.length ? SupportOutcome.RESOLVED : SupportOutcome.ABANDONED;
}

/** A data: URL for reply audio, with the type sniffed from the base64 header. */
export function audioDataUrl(b64: string): string {
  const mime = b64.startsWith('UklGR') ? 'audio/wav' : b64.startsWith('T2dn') ? 'audio/ogg' : 'audio/mpeg';
  return `data:${mime};base64,${b64}`;
}
