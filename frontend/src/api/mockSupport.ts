/**
 * Dev-only scripted customer-service backend (VITE_MOCK=1). Every customer, loan and reference is an
 * invented SAMPLE that mirrors the simulator seed shapes; nothing here is shown outside mock mode.
 */
import type {
  OfferAnswer,
  OfferBody,
  OpsRecord,
  RecordKind,
  SimAudioResult,
  SimTurn,
  SupportCall,
  SupportCallSummary,
  SupportChannel,
  SupportOutcome,
  SupportTurn,
  SupportVoiceHandlers,
  TurnMeta,
} from './support';
import type { VoiceSession } from './voice';
import { ApiError } from './errors';

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

export const SAMPLE_VERIFIED_CALL = sampleCall('sample-call-repayment', 'VOICE', REPAYMENT_SCRIPT, 42, 'TICKET_CREATED');
export const SAMPLE_ROUTED_CALL = sampleCall('sample-call-routed', 'SIM_AUDIO', ROUTED_SCRIPT, 18, 'ROUTED');

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
  ],
  escalation: [
    { ref: 'ESC-70200', kind: 'escalation', category: null, status: 'OPEN', summary: 'Unauthorised card debit', customer_ref: 'CUST-1008', call_id: 'sample-call-escalation', created_at: ago(6), escalated: null },
  ],
};

const calls = new Map<string, SupportCall>();
const progress = new Map<string, number>();
let seq = 0;

function seed() {
  if (calls.size) return;
  for (const c of [SAMPLE_VERIFIED_CALL, SAMPLE_ROUTED_CALL, sampleCall('sample-call-escalation', 'VOICE', ESCALATION_SCRIPT, 7, 'ESCALATED')]) {
    calls.set(c.id, structuredClone(c));
  }
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
    turnCount: c.turns.length, intents: [...new Set(c.turns.flatMap((t) => t.meta.intents ?? []))],
  };
}

export const mockSupport = {
  async startCall(channel: SupportChannel = 'VOICE'): Promise<{ id: string }> {
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

  async simAudio(files: File[], callId?: string): Promise<SimAudioResult> {
    await delay(500);
    const call = callId ? find(callId) : create('SIM_AUDIO');
    return { call_id: call.id, turns: files.map((f) => advance(call, f.name)) };
  },

  async supportOffer(_body: OfferBody): Promise<OfferAnswer> {
    await delay();
    return { sdp: '', type: 'answer', pc_id: 'sample-pc', call_id: create('VOICE').id };
  },

  async listRecords(kind: RecordKind): Promise<OpsRecord[]> {
    await delay();
    return structuredClone(SAMPLE_RECORDS[kind]);
  },

  /** No WebRTC in mock mode: the scripted repayment call plays itself, one exchange every 2.5 s. */
  async connectSupportVoice(callId: string | undefined, _audio: HTMLAudioElement | null, h: SupportVoiceHandlers): Promise<VoiceSession> {
    await delay(300);
    const call = callId ? find(callId) : create('VOICE');
    h.onCallId(call.id);
    const timer = setInterval(() => {
      if (call.endedAt || (progress.get(call.id) ?? 0) >= REPAYMENT_SCRIPT.length) {
        clearInterval(timer);
        return;
      }
      advance(call, 'mic');
    }, 2500);
    return {
      disconnect: async () => {
        clearInterval(timer);
        h.onDisconnected();
      },
    };
  },
};
