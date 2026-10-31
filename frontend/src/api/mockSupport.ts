/**
 * Dev-only scripted customer-service backend (VITE_MOCK=1). Every customer, loan and reference is an
 * invented SAMPLE that mirrors the simulator seed shapes; nothing here is shown outside mock mode.
 */
import type {
  CallRating,
  CustomerProfile,
  Insights,
  Lesson,
  OfferAnswer,
  OfferBody,
  OpsRecord,
  RecordKind,
  ReviewItem,
  SimAudioResult,
  SimTurn,
  SupportCall,
  SupportCallSummary,
  SupportChannel,
  SupportOutcome,
  SupportTurn,
  SupportVoiceHandlers,
  TurnFeedback,
  TurnMeta,
} from './support';
import type { VoiceSession } from './voice';
import { currentUsername } from './client';
import { FeedbackVerdict, LessonStatus, RatingSource, ReviewReason, SupportChannel as Channel, SupportOutcome as Outcome, TurnRole } from '../vocab';
import { ApiError } from './errors';
import { LessonLength } from '../vocab';

const delay = (ms = 120) => new Promise((r) => setTimeout(r, ms));
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const inDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

type Step = { role: SupportTurn['role']; text: string; meta: TurnMeta };

const PERSONAL_LOAN = {
  loan_id: 'PL-31002', product: 'Personal loan', product_type: 'personal', outstanding_principal: 284_300,
  next_instalment: { amount: 12_450, due_date: inDays(5) }, overdue: null, status: 'ACTIVE',
};
const VEHICLE_LOAN = {
  loan_id: 'VL-31003', product: 'Vehicle loan', product_type: 'vehicle', outstanding_principal: 412_900,
  next_instalment: { amount: 9_800, due_date: inDays(12) }, overdue: null, status: 'ACTIVE',
};

/** The sample customer the scripted calls verify, as the simulator's ops profile returns it. */
export const SAMPLE_PROFILE: CustomerProfile = {
  customer: { customer_ref: 'CUST-1002', first_name: 'Rahul', last_name: 'Iyer', mobile: '9876500002', dob: '1985-11-03' },
  accounts: [{ account_id: 'ACC-20002', type: 'SAVINGS', masked_number: '••• ••• 4012', balance: 85_400, currency: 'INR' }],
  loans: [
    { ...PERSONAL_LOAN, product: 'Personal Loan' },
    { ...VEHICLE_LOAN, product: 'Vehicle Loan' },
  ],
  applications: [],
  transactions: [],
  policies: [],
  claims: [],
  tickets: [{ ref: 'SR-40102', category: 'STATEMENT', status: 'IN_PROGRESS', summary: 'Account statement request for last 6 months' }],
  complaints: [],
};

/** Verified repayment call with a mid-call correction and a ticket (sample customer CUST-1002). */
export const REPAYMENT_SCRIPT: Step[] = [
  { role: 'customer', text: 'Hi, when is my next EMI due?', meta: { intents: ['REPAYMENT'], intent_source: 'llm', verified: false, verify_failures: 0, locked: false, no_speech: false } },
  { role: 'agent', text: 'I can help with that. Before I share loan details, please tell me your registered mobile number and date of birth.', meta: { tool_trace: [], retrieved: {}, refs: [] } },
  { role: 'customer', text: 'It is 98765 00002, and I was born on the third of November 1985.', meta: { intents: ['REPAYMENT'], intent_source: 'rules', verified: true, verify_failures: 0, locked: false, no_speech: false } },
  {
    role: 'agent',
    text: `Thank you, Rahul, you are verified. Your next personal loan instalment is ₹12,450, due on ${PERSONAL_LOAN.next_instalment.due_date}.`,
    meta: {
      tool_trace: [
        { name: 'verify_customer', args: { mobile: '98XXXXXX02', dob: '1985-11-03' }, result_summary: 'Verified CUST-1002' },
        { name: 'get_loans', args: { type: 'personal' }, result_summary: '1 loan: PL-31002' },
      ],
      retrieved: {
        verify_customer: { customer: { customer_ref: 'CUST-1002', first_name: 'Rahul' }, expires_in: 900 },
        get_loans: { items: [PERSONAL_LOAN] },
      },
      refs: [],
    },
  },
  { role: 'customer', text: 'No, I meant my vehicle loan, not the personal loan.', meta: { intents: ['REPAYMENT'], intent_source: 'llm', verified: true, verify_failures: 0, locked: false, no_speech: false } },
  {
    role: 'agent',
    text: `Got it. Your vehicle loan instalment is ₹9,800, due on ${VEHICLE_LOAN.next_instalment.due_date}. Nothing is overdue.`,
    meta: {
      tool_trace: [{ name: 'get_loans', args: { type: 'vehicle' }, result_summary: '1 loan: VL-31003' }],
      retrieved: { get_loans: { items: [VEHICLE_LOAN] } },
      refs: [],
    },
  },
  { role: 'customer', text: 'Can you send me the repayment schedule for it?', meta: { intents: ['SERVICE_REQUEST'], intent_source: 'llm', verified: true, verify_failures: 0, locked: false, no_speech: false } },
  {
    role: 'agent',
    text: 'I have raised a request for your vehicle loan repayment schedule. Your reference is SR-40200, and it should reach you within 2 working days.',
    meta: {
      tool_trace: [{ name: 'create_service_request', args: { category: 'REPAYMENT_SCHEDULE', summary: 'Repayment schedule for VL-31003' }, result_summary: 'Created SR-40200' }],
      retrieved: { create_service_request: { ref: 'SR-40200', status: 'OPEN', eta_days: 2 } },
      refs: ['SR-40200'],
    },
  },
];

/** A gold-rate question the bank does not support: refused politely and routed (sample customer CUST-1001). */
export const ROUTED_SCRIPT: Step[] = [
  { role: 'customer', text: '', meta: { intents: [], verified: false, verify_failures: 0, locked: false, no_speech: true } },
  { role: 'customer', text: 'What is the gold rate in Mumbai today?', meta: { intents: ['UNSUPPORTED'], intent_source: 'rules', verified: false, verify_failures: 0, locked: false, no_speech: false } },
  {
    role: 'agent',
    text: 'I am sorry, I cannot help with gold rates on this line. I have passed your question to our team with reference RQ-60200, and someone will follow up.',
    meta: {
      tool_trace: [{ name: 'route_unsupported', args: { reason: 'Gold rate enquiry is outside supported services', query_text: 'What is the gold rate in Mumbai today?' }, result_summary: 'Routed as RQ-60200' }],
      retrieved: { route_unsupported: { ref: 'RQ-60200' } },
      refs: ['RQ-60200'],
    },
  },
];

const ESCALATION_SCRIPT: Step[] = [
  { role: 'customer', text: 'There is a card payment of 48,999 rupees I never made.', meta: { intents: ['COMPLAINT'], intent_source: 'llm', verified: true, verify_failures: 0, locked: false, no_speech: false } },
  {
    role: 'agent',
    text: 'I am sorry to hear that. I have registered complaint CMP-50200 for an unauthorised transaction and escalated it to a specialist, reference ESC-70200.',
    meta: {
      tool_trace: [
        { name: 'get_transactions', args: { ref: 'TXN-90011' }, result_summary: '1 transaction, POSTED' },
        { name: 'register_complaint', args: { category: 'UNAUTHORISED_TRANSACTION', severity: 'HIGH' }, result_summary: 'Created CMP-50200, escalated' },
        { name: 'escalate_to_human', args: { reason: 'Unauthorised card debit' }, result_summary: 'Created ESC-70200' },
      ],
      retrieved: {
        get_transactions: { items: [{ ref: 'TXN-90011', date: inDays(-2), description: 'Card purchase', amount: 48_999, direction: 'DEBIT', status: 'POSTED', recorded_reason: null }] },
        register_complaint: { ref: 'CMP-50200', status: 'OPEN', escalated: true },
        escalate_to_human: { ref: 'ESC-70200' },
      },
      refs: ['CMP-50200', 'ESC-70200'],
    },
  },
];

function materialise(steps: Step[], startMin: number): SupportTurn[] {
  return steps.map((s, i) => ({ seq: i + 1, role: s.role, text: s.text, at: ago(startMin - i * 0.4), meta: structuredClone(s.meta) }));
}

function sampleCall(id: string, channel: SupportChannel, steps: Step[], startMin: number, outcome: SupportOutcome | null): SupportCall {
  const turns = materialise(steps, startMin);
  return {
    id,
    channel,
    startedAt: ago(startMin + 0.3),
    endedAt: outcome ? ago(startMin - steps.length * 0.4) : null,
    outcome,
    verified: turns.some((t) => t.meta.verified),
    turns,
  };
}

export const SAMPLE_VERIFIED_CALL: SupportCall = {
  ...sampleCall('sample-call-repayment', 'VOICE', REPAYMENT_SCRIPT, 42, 'TICKET_CREATED'),
  rating: { score: 5, comment: 'Quick, and it caught that I meant the vehicle loan.', source: 'VOICE', at: ago(36) },
};
SAMPLE_VERIFIED_CALL.turns[3].feedback = [{ seq: 4, verdict: 'GOOD', correction: null, author: 'reviewer', at: ago(30) }];

export const SAMPLE_ROUTED_CALL: SupportCall = {
  ...sampleCall('sample-call-routed', 'SIM_AUDIO', ROUTED_SCRIPT, 18, 'ROUTED'),
  rating: { score: 2, comment: 'It could not tell me anything about gold.', source: 'VOICE', at: ago(16) },
};
SAMPLE_ROUTED_CALL.turns[2].feedback = [
  {
    seq: 3,
    verdict: 'BAD',
    correction: 'Say that live gold prices are not available here, then offer our gold loan interest rates from the FAQ before routing the question.',
    author: 'reviewer',
    at: ago(12),
  },
];

export const SAMPLE_ESCALATION_CALL = sampleCall('sample-call-escalation', 'VOICE', ESCALATION_SCRIPT, 7, 'ESCALATED');

export const SAMPLE_LESSONS: Lesson[] = [
  {
    id: 'LSN-3', text: 'When a caller asks for gold prices, say live rates are not available and offer the gold loan interest rate FAQ before routing.',
    status: 'PROPOSED', sourceCallId: SAMPLE_ROUTED_CALL.id, sourceSeq: 3, author: 'reviewer', approvedBy: null, createdAt: ago(11),
  },
  {
    id: 'LSN-2', text: 'Repeat the loan type back to the caller before reading out an instalment amount when they have more than one loan.',
    status: 'PROPOSED', sourceCallId: SAMPLE_VERIFIED_CALL.id, sourceSeq: 4, author: 'reviewer', approvedBy: null, createdAt: ago(60 * 3),
  },
  {
    id: 'LSN-1', text: 'For an unauthorised card debit, register the complaint and escalate in the same turn; do not ask the caller to call back.',
    status: 'ACTIVE', sourceCallId: 'sample-call-escalation', sourceSeq: 2, author: 'reviewer', approvedBy: 'admin', createdAt: ago(60 * 26),
  },
];

export const SAMPLE_RECORDS: Record<RecordKind, OpsRecord[]> = {
  ticket: [
    { ref: 'SR-40200', kind: 'ticket', category: 'REPAYMENT_SCHEDULE', status: 'OPEN', summary: 'Repayment schedule for VL-31003', customer_ref: 'CUST-1002', call_id: SAMPLE_VERIFIED_CALL.id, created_at: ago(39), escalated: null },
    { ref: 'SR-40102', kind: 'ticket', category: 'STATEMENT', status: 'IN_PROGRESS', summary: 'Savings account statement for the last quarter', customer_ref: 'CUST-1002', call_id: null, created_at: ago(60 * 26), escalated: null },
  ],
  complaint: [
    { ref: 'CMP-50200', kind: 'complaint', category: 'UNAUTHORISED_TRANSACTION', status: 'OPEN', summary: 'Card debit TXN-90011 not made by the customer', customer_ref: 'CUST-1008', call_id: 'sample-call-escalation', created_at: ago(6), escalated: true },
    { ref: 'CMP-50011', kind: 'complaint', category: 'INCORRECT_CHARGE', status: 'OPEN', summary: 'Processing fee charged twice on home loan', customer_ref: 'CUST-1006', call_id: null, created_at: ago(60 * 50), escalated: false },
  ],
  routed: [
    { ref: 'RQ-60200', kind: 'routed', category: null, status: null, summary: 'What is the gold rate in Mumbai today? — Gold rate enquiry is outside supported services', customer_ref: null, call_id: SAMPLE_ROUTED_CALL.id, created_at: ago(17), escalated: null },
    { ref: 'RQ-60199', kind: 'routed', category: null, status: null, summary: 'Can you book me a flight to Dubai? — Travel booking is not a bank service', customer_ref: 'CUST-1002', call_id: null, created_at: ago(55), escalated: null },
    { ref: 'RQ-60198', kind: 'routed', category: null, status: null, summary: 'What are your gold loan rates? — No approved FAQ answer', customer_ref: null, call_id: null, created_at: ago(90), escalated: null },
    { ref: 'RQ-60197', kind: 'routed', category: null, status: null, summary: 'Give me some stock tips. — Investment advice is outside supported services', customer_ref: null, call_id: null, created_at: ago(140), escalated: null },
    { ref: 'RQ-60196', kind: 'routed', category: null, status: null, summary: 'Book flight tickets for me, please! — Travel booking is not a bank service', customer_ref: null, call_id: null, created_at: ago(200), escalated: null },
    { ref: 'RQ-60195', kind: 'routed', category: null, status: null, summary: 'Which stocks should I buy this week? — Investment advice is outside supported services', customer_ref: null, call_id: null, created_at: ago(260), escalated: null },
    { ref: 'RQ-60194', kind: 'routed', category: null, status: null, summary: 'Gold loan interest rate? — No approved FAQ answer', customer_ref: null, call_id: null, created_at: ago(320), escalated: null },
  ],
  escalation: [
    { ref: 'ESC-70200', kind: 'escalation', category: null, status: 'OPEN', summary: 'Unauthorised card debit', customer_ref: 'CUST-1008', call_id: 'sample-call-escalation', created_at: ago(6), escalated: null },
  ],
};

const calls = new Map<string, SupportCall>();
const progress = new Map<string, number>();
const resolved = new Map<string, string>();
const paused = new Set<string>();
let lessons: Lesson[] = [];
let seq = 0;
let lessonSeq = SAMPLE_LESSONS.length;

function seed() {
  if (calls.size) return;
  for (const c of [SAMPLE_VERIFIED_CALL, SAMPLE_ROUTED_CALL, SAMPLE_ESCALATION_CALL]) {
    calls.set(c.id, structuredClone(c));
  }
  resolved.set(SAMPLE_ESCALATION_CALL.id, 'Complaint and escalation were correct; the customer was upset about the debit, not the agent.');
  lessons = structuredClone(SAMPLE_LESSONS);
}

const LOW_SCORE = 2;
const UNHAPPY = new Set<SupportOutcome>([Outcome.ESCALATED, Outcome.COMPLAINT_REGISTERED]);

/** Mirrors the API's review rules: low ratings, unhappy endings and BAD feedback. */
export function reviewReasons(c: SupportCall): ReviewItem['reasons'] {
  const reasons: ReviewItem['reasons'] = [];
  if (c.rating && c.rating.score <= LOW_SCORE) reasons.push(ReviewReason.LOW_RATING);
  if (c.outcome && UNHAPPY.has(c.outcome)) reasons.push(ReviewReason.DISSATISFIED);
  if (c.turns.some((t) => t.feedback?.some((f) => f.verdict === FeedbackVerdict.BAD))) reasons.push(ReviewReason.BAD_FEEDBACK);
  return reasons;
}

function create(channel: SupportChannel): SupportCall {
  seed();
  const call: SupportCall = { id: `sample-live-${++seq}`, channel, startedAt: new Date().toISOString(), endedAt: null, outcome: null, verified: false, turns: [] };
  calls.set(call.id, call);
  progress.set(call.id, 0);
  return call;
}

function find(id: string): SupportCall {
  seed();
  const c = calls.get(id);
  if (!c) throw new ApiError({ status: 404, title: 'Not found', detail: `No call ${id}` });
  return c;
}

function push(call: SupportCall, step: Step) {
  call.turns.push({ seq: call.turns.length + 1, role: step.role, text: step.text, at: new Date().toISOString(), meta: structuredClone(step.meta) });
  if (step.meta.verified) call.verified = true;
}

/** Plays the next customer step (and its agent reply) from the repayment script. */
function advance(call: SupportCall, fileName: string): SimTurn {
  if (/noise|silence|silent/i.test(fileName)) {
    push(call, ROUTED_SCRIPT[0]);
    return { file: fileName, transcript: '', no_speech: true, intents: [], verified: call.verified, tool_trace: [], retrieved: {}, reply_text: null, reply_audio_b64: null };
  }
  let i = progress.get(call.id) ?? 0;
  if (i >= REPAYMENT_SCRIPT.length) i = 0;
  const customer = REPAYMENT_SCRIPT[i];
  const agent = REPAYMENT_SCRIPT[i + 1];
  push(call, customer);
  push(call, agent);
  progress.set(call.id, i + 2);
  return {
    file: fileName,
    transcript: customer.text,
    no_speech: false,
    intents: customer.meta.intents ?? [],
    verified: !!customer.meta.verified,
    tool_trace: agent.meta.tool_trace ?? [],
    retrieved: agent.meta.retrieved ?? {},
    reply_text: agent.text,
    reply_audio_b64: null,
  };
}

function summarise(c: SupportCall): SupportCallSummary {
  return {
    id: c.id, channel: c.channel, startedAt: c.startedAt, endedAt: c.endedAt, outcome: c.outcome, verified: c.verified,
    turnCount: c.turns.length, intents: [...new Set(c.turns.flatMap((t) => t.meta.intents ?? []))], rating: c.rating ?? null,
  };
}

export const mockSupport = {
  async startCall(channel: SupportChannel = Channel.VOICE): Promise<{ id: string }> {
    await delay();
    return { id: create(channel).id };
  },

  async getCall(id: string): Promise<SupportCall> {
    await delay(60);
    return structuredClone(find(id));
  },

  async listCalls(outcome?: SupportOutcome): Promise<SupportCallSummary[]> {
    await delay();
    seed();
    return [...calls.values()]
      .filter((c) => !outcome || c.outcome === outcome)
      .sort((a, b) => b.startedAt.localeCompare(a.startedAt))
      .map(summarise);
  },

  async endCall(id: string, outcome: SupportOutcome): Promise<unknown> {
    await delay();
    const c = find(id);
    c.outcome = outcome;
    c.endedAt = new Date().toISOString();
    return {};
  },

  async rateCall(id: string, score: number, comment: string | null, source: RatingSource = RatingSource.PANEL): Promise<CallRating> {
    await delay();
    if (!Number.isInteger(score) || score < 1 || score > 5) throw new ApiError({ status: 400, title: 'Invalid rating', detail: 'Score must be 1 to 5.' });
    const rating: CallRating = { score, comment, source, at: new Date().toISOString() };
    find(id).rating = rating;
    return structuredClone(rating);
  },

  async sendFeedback(id: string, turnSeq: number, verdict: FeedbackVerdict, correction: string | null): Promise<TurnFeedback> {
    await delay();
    const turn = find(id).turns.find((t) => t.seq === turnSeq);
    if (!turn || turn.role !== TurnRole.AGENT) throw new ApiError({ status: 400, title: 'Not an agent turn', detail: 'Feedback is for agent turns only.' });
    const author = currentUsername() ?? 'reviewer';
    const fb: TurnFeedback = { seq: turnSeq, verdict, correction, author, at: new Date().toISOString() };
    turn.feedback = [...(turn.feedback ?? []).filter((f) => f.author !== author), fb];
    return structuredClone(fb);
  },

  async listReview(): Promise<ReviewItem[]> {
    await delay();
    seed();
    return [...calls.values()]
      .map((c) => ({ id: c.id, startedAt: c.startedAt, outcome: c.outcome, rating: c.rating?.score ?? null, reasons: reviewReasons(c), resolved: resolved.has(c.id) }))
      .filter((r) => r.reasons.length > 0)
      .sort((a, b) => Number(a.resolved) - Number(b.resolved) || b.startedAt.localeCompare(a.startedAt));
  },

  async resolveReview(id: string, note: string): Promise<unknown> {
    await delay();
    find(id);
    resolved.set(id, note);
    return {};
  },

  async listLessons(activeOnly = false): Promise<Lesson[]> {
    await delay();
    seed();
    return structuredClone(lessons.filter((l) => !activeOnly || l.status === LessonStatus.ACTIVE));
  },

  async proposeLesson(text: string, sourceCallId: string | null = null, sourceSeq: number | null = null): Promise<Lesson> {
    await delay();
    seed();
    const n = text.trim().length;
    if (n < LessonLength.MIN || n > LessonLength.MAX) throw new ApiError({ status: 400, title: 'Invalid lesson', detail: `A lesson is ${LessonLength.MIN} to ${LessonLength.MAX} characters.` });
    const lesson: Lesson = {
      id: `LSN-${++lessonSeq}`, text: text.trim(), status: LessonStatus.PROPOSED, sourceCallId, sourceSeq,
      author: currentUsername() ?? 'reviewer', approvedBy: null, createdAt: new Date().toISOString(),
    };
    lessons = [lesson, ...lessons];
    return structuredClone(lesson);
  },

  async setLessonStatus(id: string, status: typeof LessonStatus.ACTIVE | typeof LessonStatus.RETIRED): Promise<Lesson> {
    await delay();
    seed();
    const l = lessons.find((x) => x.id === id);
    if (!l) throw new ApiError({ status: 404, title: 'Not found', detail: `No lesson ${id}` });
    l.status = status;
    if (status === LessonStatus.ACTIVE) l.approvedBy = currentUsername() ?? 'admin';
    return structuredClone(l);
  },

  async getInsights(): Promise<Insights> {
    await delay();
    seed();
    const all = [...calls.values()];
    const scores = all.flatMap((c) => (c.rating ? [c.rating.score] : []));
    const distribution: Record<string, number> = { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 };
    scores.forEach((n) => (distribution[String(n)] += 1));
    const bad = all.reduce((n, c) => n + c.turns.reduce((m, t) => m + (t.feedback ?? []).filter((f) => f.verdict === FeedbackVerdict.BAD).length, 0), 0);
    return {
      ratings: { count: scores.length, average: scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null, distribution },
      lowRated: scores.filter((n) => n <= LOW_SCORE).length,
      openReviews: all.filter((c) => reviewReasons(c).length > 0 && !resolved.has(c.id)).length,
      badFeedback: bad,
      activeLessons: lessons.filter((l) => l.status === LessonStatus.ACTIVE).length,
    };
  },

  async simAudio(files: File[], callId?: string): Promise<SimAudioResult> {
    await delay(500);
    const call = callId ? find(callId) : create(Channel.SIM_AUDIO);
    return { call_id: call.id, turns: files.map((f) => advance(call, f.name)) };
  },

  async supportOffer(_body: OfferBody): Promise<OfferAnswer> {
    await delay();
    return { sdp: '', type: 'answer', pc_id: 'sample-pc', call_id: create(Channel.VOICE).id };
  },

  async getCustomerProfile(customerRef: string): Promise<CustomerProfile> {
    await delay();
    if (customerRef !== SAMPLE_PROFILE.customer.customer_ref) throw new ApiError({ status: 404, title: 'No customer with that reference.' });
    return structuredClone(SAMPLE_PROFILE);
  },

  async listRecords(kind: RecordKind): Promise<OpsRecord[]> {
    await delay();
    return structuredClone(SAMPLE_RECORDS[kind]);
  },

  async pauseCall(callId: string, on: boolean): Promise<void> {
    await delay();
    if (on) paused.add(callId);
    else paused.delete(callId);
  },

  /** No WebRTC in mock mode: the scripted repayment call plays itself, one exchange every 2.5 s, except while paused. */
  async connectSupportVoice(callId: string | undefined, _audio: HTMLAudioElement | null, h: SupportVoiceHandlers): Promise<VoiceSession> {
    await delay(300);
    const call = callId ? find(callId) : create(Channel.VOICE);
    h.onCallId(call.id);
    const timer = setInterval(() => {
      if (call.endedAt || (progress.get(call.id) ?? 0) >= REPAYMENT_SCRIPT.length) {
        clearInterval(timer);
        return;
      }
      if (!paused.has(call.id)) advance(call, 'mic');
    }, 2500);
    return {
      disconnect: async () => {
        clearInterval(timer);
        paused.delete(call.id);
        h.onDisconnected();
      },
      setMicEnabled: () => undefined,
    };
  },
};
