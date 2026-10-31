import { ApiError, toApiError } from './errors';
import { get, MOCK_MODE, patchJson, postJson } from './client';
import { VOICE_BASE } from './renewals';
import { describeVoiceError, type VoiceSession } from './voice';
import { mockSupport } from './mockSupport';
import { CoreApiPath } from './paths/core';
import { opsCustomerPath, SimulatorPath } from './paths/simulator';
import { supportPausePath, turnAudioPath, VoicePath } from './paths/voice';
import {
  FeedbackVerdict,
  Intent,
  IntentSource,
  LegacyIntent,
  LessonStatus,
  RatingSource,
  RecordKind,
  RefPrefix,
  ReviewReason,
  SupportChannel,
  SupportOutcome,
  TurnRole,
  Verification,
} from '../vocab';

export { FeedbackVerdict, LessonStatus, RatingSource, RecordKind, ReviewReason, SupportChannel, SupportOutcome, Verification };

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
  audio?: boolean;
  tool_trace?: ToolTrace[];
  retrieved?: Record<string, unknown>;
  refs?: string[];
  [key: string]: unknown;
}

export interface CallRating {
  score: number;
  comment: string | null;
  source: RatingSource;
  at: string;
}

export interface TurnFeedback {
  seq: number;
  verdict: FeedbackVerdict;
  correction: string | null;
  author: string;
  at: string;
}

export interface SupportTurn {
  seq: number;
  role: TurnRole;
  text: string;
  at: string;
  meta: TurnMeta;
  feedback?: TurnFeedback[];
}

export interface ReviewItem {
  id: string;
  startedAt: string;
  outcome: SupportOutcome | null;
  /** The call's rating score, if any (the API may send the rating object; normalised to its score). */
  rating: number | null;
  reasons: ReviewReason[];
  resolved: boolean;
}

export interface Lesson {
  id: string;
  text: string;
  status: LessonStatus;
  sourceCallId: string | null;
  sourceSeq: number | null;
  author: string;
  approvedBy: string | null;
  createdAt: string;
}

export interface Insights {
  ratings: { count: number; average: number | null; distribution: Record<string, number> };
  lowRated: number;
  openReviews: number;
  badFeedback: number;
  activeLessons: number;
}


export interface SupportCall {
  id: string;
  channel: SupportChannel;
  startedAt: string;
  endedAt: string | null;
  outcome: SupportOutcome | null;
  verified: boolean;
  turns: SupportTurn[];
  rating?: CallRating | null;
}

/** GET /v1/ops/customers/{ref} on the bank simulator: what the bank holds for one customer. */
export interface CustomerProfile {
  customer: { customer_ref: string; first_name: string; last_name: string; mobile: string; dob: string };
  accounts: { account_id: string; type: string; masked_number: string; balance: number; currency: string }[];
  loans: {
    loan_id: string;
    product: string;
    outstanding_principal: number;
    next_instalment: { amount: number; due_date: string } | null;
    overdue: { amount: number; since: string } | null;
    status: string;
  }[];
  applications: { ref: string; product: string; amount: number; stage_label: string; submitted_on: string }[];
  transactions: { ref: string; date: string; description: string; amount: number; direction: string; status: string }[];
  policies: { policy_no: string; product: string; status: string; premium: number; coverage_status: string }[];
  claims: { claim_no: string; policy_no: string; status: string; amount_claimed: number }[];
  tickets: { ref: string; category: string; status: string; summary: string }[];
  complaints: { ref: string; category: string; status: string; description: string; escalated: boolean }[];
}

const VERIFY_TOOL = 'verify_customer';

/** The customer the agent verified on this call (the latest successful verify_customer), or null before verification. */
export function verifiedCustomerRef(turns: SupportTurn[]): string | null {
  for (let i = turns.length - 1; i >= 0; i--) {
    const result = turns[i].meta.retrieved?.[VERIFY_TOOL] as { verified?: boolean; customer?: { customer_ref?: string } } | undefined;
    const ref = result?.customer?.customer_ref;
    if (ref && result?.verified !== false) return ref;
  }
  return null;
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
  rating?: CallRating | null;
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
    rating: c.rating ?? null,
    turns: (Array.isArray(c.turns) ? c.turns : []).map((t) => ({ ...t, meta: t.meta ?? {}, feedback: t.feedback ?? [] })),
  };
}

function normaliseReview(r: Omit<ReviewItem, 'rating'> & { rating?: number | { score?: number } | null }): ReviewItem {
  const rating = typeof r.rating === 'number' ? r.rating : r.rating?.score ?? null;
  return { ...r, outcome: r.outcome ?? null, rating, reasons: r.reasons ?? [], resolved: !!r.resolved };
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
    return (r?.items ?? []).map((c) => ({ ...c, intents: c.intents ?? [], rating: c.rating ?? null }));
  },

  async endCall(id: string, outcome: SupportOutcome): Promise<unknown> {
    try {
      return await postJson(CoreApiPath.supportCallEnd(id), { outcome });
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.detail === 'CALL_ALREADY_ENDED')) {
        return { id, outcome, alreadyEnded: true };
      }
      throw e;
    }
  },

  /* ---------- ratings, feedback, review and lessons ---------- */

  rateCall(id: string, score: number, comment: string | null, source: RatingSource = RatingSource.PANEL): Promise<CallRating> {
    return postJson(CoreApiPath.supportCallRating(id), { score, comment, source });
  },

  sendFeedback(id: string, seq: number, verdict: FeedbackVerdict, correction: string | null): Promise<TurnFeedback> {
    return postJson(CoreApiPath.turnFeedback(id, seq), { verdict, correction });
  },

  async listReview(): Promise<ReviewItem[]> {
    const r = await get<{ items?: Parameters<typeof normaliseReview>[0][] }>(`${CoreApiPath.SUPPORT_REVIEW}?limit=50`);
    return (r?.items ?? []).map(normaliseReview);
  },

  resolveReview(id: string, note: string): Promise<unknown> {
    return postJson(CoreApiPath.reviewResolve(id), { note });
  },

  async listLessons(activeOnly = false): Promise<Lesson[]> {
    const r = await get<{ items?: Lesson[] }>(activeOnly ? `${CoreApiPath.SUPPORT_LESSONS}?active=true` : CoreApiPath.SUPPORT_LESSONS);
    return r?.items ?? [];
  },

  proposeLesson(text: string, sourceCallId: string | null = null, sourceSeq: number | null = null): Promise<Lesson> {
    return postJson(CoreApiPath.SUPPORT_LESSONS, { text, sourceCallId, sourceSeq });
  },

  setLessonStatus(id: string, status: typeof LessonStatus.ACTIVE | typeof LessonStatus.RETIRED): Promise<Lesson> {
    return patchJson(CoreApiPath.lesson(id), { status });
  },

  getInsights(): Promise<Insights> {
    return get<Insights>(CoreApiPath.SUPPORT_INSIGHTS);
  },

  /* ---------- voice service ---------- */

  async simAudio(files: File[], callId?: string): Promise<SimAudioResult> {
    const form = new FormData();
    files.forEach((f) => form.append('files', f, f.name));
    if (callId) form.append('call_id', callId);
    const res = await reach('voice service', VOICE_BASE, () => fetch(`${VOICE_BASE}${VoicePath.SIM_AUDIO}`, { method: 'POST', body: form }));
    return (await res.json()) as SimAudioResult;
  },

  /** While paused the agent ignores the caller's audio and does not hang up on silence. */
  async pauseCall(callId: string, paused: boolean): Promise<void> {
    await reach('voice service', VOICE_BASE, () =>
      fetch(`${VOICE_BASE}${supportPausePath(callId)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paused }),
      }),
    );
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

  async getCustomerProfile(customerRef: string): Promise<CustomerProfile> {
    const res = await reach('bank simulator', SIMULATOR_BASE, () =>
      fetch(`${SIMULATOR_BASE}${opsCustomerPath(customerRef)}`, {
        headers: { Accept: 'application/json', Authorization: 'Basic ' + btoa('ops:ops') },
      }),
    );
    return (await res.json()) as CustomerProfile;
  },

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
/** Browser-side clean-up of the caller's microphone: background noise, the agent's own voice (echo) and level swings. */
export const MIC_CONSTRAINTS: MediaTrackConstraints = { noiseSuppression: true, echoCancellation: true, autoGainControl: true };

export const turnAudioUrl = (callId: string, seq: number) => `${VOICE_BASE}${turnAudioPath(callId, seq)}`;

export async function cleanMicrophone(track: MediaStreamTrack): Promise<void> {
  try {
    await track.applyConstraints(MIC_CONSTRAINTS);
  } catch {
    /* a browser that can't apply them keeps the raw microphone */
  }
}

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
        if (track.kind === 'audio' && participant?.local) {
          void cleanMicrophone(track);
          return;
        }
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
  return { disconnect: () => client.disconnect(), setMicEnabled: (on) => client.enableMic(on) };
}

export type SupportApi = typeof liveSupport;

const api: SupportApi = MOCK_MODE ? (mockSupport as SupportApi) : liveSupport;

export const startCall = (channel?: SupportChannel) => api.startCall(channel);
export const getCall = (id: string) => api.getCall(id);
export const listCalls = (outcome?: SupportOutcome) => api.listCalls(outcome);
export const endCall = (id: string, outcome: SupportOutcome) => api.endCall(id, outcome);
export const simAudio = (files: File[], callId?: string) => api.simAudio(files, callId);
export const supportOffer = (body: OfferBody) => api.supportOffer(body);
export const pauseCall = (id: string, paused: boolean) => api.pauseCall(id, paused);
export const listRecords = (kind: RecordKind) => api.listRecords(kind);
export const getCustomerProfile = (customerRef: string) => api.getCustomerProfile(customerRef);
export const rateCall = (id: string, score: number, comment: string | null) => api.rateCall(id, score, comment, RatingSource.PANEL);
export const sendFeedback = (id: string, seq: number, verdict: FeedbackVerdict, correction: string | null) =>
  api.sendFeedback(id, seq, verdict, correction);
export const listReview = () => api.listReview();
export const resolveReview = (id: string, note: string) => api.resolveReview(id, note);
export const listLessons = (activeOnly?: boolean) => api.listLessons(activeOnly);
export const proposeLesson = (text: string, sourceCallId?: string | null, sourceSeq?: number | null) =>
  api.proposeLesson(text, sourceCallId ?? null, sourceSeq ?? null);
export const setLessonStatus = (id: string, status: typeof LessonStatus.ACTIVE | typeof LessonStatus.RETIRED) => api.setLessonStatus(id, status);
export const getInsights = () => api.getInsights();
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
  [SupportChannel.PHONE]: 'Phone',
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
  if (refs.some((r) => r.startsWith(RefPrefix.ESCALATION))) return SupportOutcome.ESCALATED;
  if (refs.some((r) => r.startsWith(RefPrefix.COMPLAINT))) return SupportOutcome.COMPLAINT_REGISTERED;
  if (refs.some((r) => r.startsWith(RefPrefix.TICKET))) return SupportOutcome.TICKET_CREATED;
  if (refs.some((r) => r.startsWith(RefPrefix.ROUTED))) return SupportOutcome.ROUTED;
  return call.turns.length ? SupportOutcome.RESOLVED : SupportOutcome.ABANDONED;
}

/** A data: URL for reply audio, with the type sniffed from the base64 header. */
export function audioDataUrl(b64: string): string {
  const mime = b64.startsWith('UklGR') ? 'audio/wav' : b64.startsWith('T2dn') ? 'audio/ogg' : 'audio/mpeg';
  return `data:${mime};base64,${b64}`;
}

export const REVIEW_REASON_LABEL: Record<ReviewReason, string> = {
  [ReviewReason.LOW_RATING]: 'Low rating',
  [ReviewReason.DISSATISFIED]: 'Dissatisfied',
  [ReviewReason.BAD_FEEDBACK]: 'Bad answer',
};

export const LESSON_STATUS_LABEL: Record<LessonStatus, string> = {
  [LessonStatus.PROPOSED]: 'Proposed',
  [LessonStatus.ACTIVE]: 'Active',
  [LessonStatus.RETIRED]: 'Retired',
};

export const LESSON_STATUS_TONE: Record<LessonStatus, string> = {
  [LessonStatus.PROPOSED]: 'warn',
  [LessonStatus.ACTIVE]: 'ok',
  [LessonStatus.RETIRED]: 'dim',
};

export const RATING_SOURCE_LABEL: Record<RatingSource, string> = {
  [RatingSource.VOICE]: 'Rated by the customer on the call',
  [RatingSource.PANEL]: 'Added in the panel',
};
