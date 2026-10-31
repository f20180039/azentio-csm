import { ApiError, toApiError } from './errors';
import { get, MOCK_MODE, postJson } from './client';
import { VOICE_BASE } from './renewals';
import { describeVoiceError, type VoiceSession } from './voice';
import { mockSupport } from './mockSupport';

export const SIMULATOR_BASE: string =
  (import.meta.env.VITE_SIMULATOR_BASE as string | undefined) ?? 'http://localhost:8090/v1';

/* ---------- shared contract types (docs/superpowers/plans/2026-10-31-csm-voice-agent.md) ---------- */

export type SupportChannel = 'VOICE' | 'SIM_AUDIO' | 'TEXT';
export type SupportOutcome = 'RESOLVED' | 'TICKET_CREATED' | 'COMPLAINT_REGISTERED' | 'ROUTED' | 'ESCALATED' | 'ABANDONED';
export const SUPPORT_OUTCOMES: SupportOutcome[] = ['RESOLVED', 'TICKET_CREATED', 'COMPLAINT_REGISTERED', 'ROUTED', 'ESCALATED', 'ABANDONED'];

export interface ToolTrace {
  name: string;
  args: Record<string, unknown>;
  result_summary?: string | null;
}

export interface TurnMeta {
  intents?: string[];
  intent_source?: 'llm' | 'rules';
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
  role: 'customer' | 'agent';
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

export type RecordKind = 'ticket' | 'complaint' | 'routed' | 'escalation';

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
  startCall(channel: SupportChannel = 'VOICE'): Promise<{ id: string }> {
    return postJson('/support/calls', { channel });
  },

  async getCall(id: string): Promise<SupportCall> {
    return normaliseCall(await get<SupportCall>(`/support/calls/${encodeURIComponent(id)}`));
  },

  async listCalls(outcome?: SupportOutcome): Promise<SupportCallSummary[]> {
    const params = new URLSearchParams({ limit: '50' });
    if (outcome) params.set('outcome', outcome);
    const r = await get<{ items?: SupportCallSummary[] }>(`/support/calls?${params}`);
    return (r?.items ?? []).map((c) => ({ ...c, intents: c.intents ?? [] }));
  },

  endCall(id: string, outcome: SupportOutcome): Promise<unknown> {
    return postJson(`/support/calls/${encodeURIComponent(id)}/end`, { outcome });
  },

  /* ---------- voice service ---------- */

  async simAudio(files: File[], callId?: string): Promise<SimAudioResult> {
    const form = new FormData();
    files.forEach((f) => form.append('files', f, f.name));
    if (callId) form.append('call_id', callId);
    const res = await reach('voice service', VOICE_BASE, () => fetch(`${VOICE_BASE}/sim/audio`, { method: 'POST', body: form }));
    return (await res.json()) as SimAudioResult;
  },

  async supportOffer(body: OfferBody, fetchImpl: typeof fetch = fetch): Promise<OfferAnswer> {
    const res = await reach('voice service', VOICE_BASE, () =>
      fetchImpl(`${VOICE_BASE}/support/offer`, {
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
      fetch(`${SIMULATOR_BASE}/ops/records?kind=${kind}`, {
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
  const endpoint = `${VOICE_BASE}/support/offer`;
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

const INTENT_LABEL: Record<string, string> = {
  LOAN_APPLICATION: 'Loan application',
  REPAYMENT: 'Repayment',
  ACCOUNT: 'Account',
  TRANSACTION: 'Transaction',
  SERVICE_REQUEST: 'Service request',
  SERVICE_REQUEST_STATUS: 'Service request status',
  PRODUCT_QUESTION: 'Product question',
  PRODUCT_INFO: 'Product question',
  FAQ: 'Product question',
  COMPLAINT: 'Complaint',
  INSURANCE: 'Insurance',
  STATEMENT: 'Statement',
  ESCALATION: 'Escalation',
  UNSUPPORTED: 'Unsupported',
  UNCLEAR: 'Unclear',
  GREETING: 'Greeting',
};

export function intentLabel(intent: string): string {
  const key = intent.toUpperCase();
  return INTENT_LABEL[key] ?? key.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}

export function intentTone(intent: string): string {
  const key = intent.toUpperCase();
  if (key === 'UNSUPPORTED') return 'warn';
  if (key === 'UNCLEAR') return 'dim';
  if (key === 'COMPLAINT' || key === 'ESCALATION') return 'bad';
  return 'neutral';
}

export const OUTCOME_LABEL: Record<SupportOutcome, string> = {
  RESOLVED: 'Resolved',
  TICKET_CREATED: 'Ticket created',
  COMPLAINT_REGISTERED: 'Complaint registered',
  ROUTED: 'Routed',
  ESCALATED: 'Escalated',
  ABANDONED: 'Abandoned',
};

export const OUTCOME_TONE: Record<SupportOutcome, string> = {
  RESOLVED: 'ok',
  TICKET_CREATED: 'info',
  COMPLAINT_REGISTERED: 'warn',
  ROUTED: 'warn',
  ESCALATED: 'bad',
  ABANDONED: 'dim',
};

export type Verification = 'NOT_VERIFIED' | 'VERIFIED' | 'LOCKED';

/** From the latest customer turn's meta; the call-level flag covers calls whose turns carry no meta yet. */
export function verificationOf(call: Pick<SupportCall, 'turns' | 'verified'>): { state: Verification; failures: number } {
  const last = [...call.turns].reverse().find((t) => t.role === 'customer' && (t.meta.verified !== undefined || t.meta.locked !== undefined));
  const failures = last?.meta.verify_failures ?? 0;
  if (last?.meta.locked) return { state: 'LOCKED', failures };
  if (last?.meta.verified || call.verified) return { state: 'VERIFIED', failures };
  return { state: 'NOT_VERIFIED', failures };
}

/** The outcome an operator most likely wants, from the references the agent created. */
export function suggestOutcome(call: Pick<SupportCall, 'turns'>): SupportOutcome {
  const refs = call.turns.flatMap((t) => t.meta.refs ?? []);
  if (refs.some((r) => r.startsWith('ESC-'))) return 'ESCALATED';
  if (refs.some((r) => r.startsWith('CMP-'))) return 'COMPLAINT_REGISTERED';
  if (refs.some((r) => r.startsWith('SR-'))) return 'TICKET_CREATED';
  if (refs.some((r) => r.startsWith('RQ-'))) return 'ROUTED';
  return call.turns.length ? 'RESOLVED' : 'ABANDONED';
}

/** A data: URL for reply audio, with the type sniffed from the base64 header. */
export function audioDataUrl(b64: string): string {
  const mime = b64.startsWith('UklGR') ? 'audio/wav' : b64.startsWith('T2dn') ? 'audio/ogg' : 'audio/mpeg';
  return `data:${mime};base64,${b64}`;
}
