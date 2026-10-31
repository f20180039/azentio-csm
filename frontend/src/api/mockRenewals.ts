/**
 * Dev-only scripted renewals backend (VITE_MOCK=1). Every policy, holder and amount is an invented SAMPLE;
 * "Lotusleaf General Insurance" is a fictional insurer.
 */
import { CallOutcome, CallTurnRole, RenewalRoute } from '../vocab';
import type { CallView, QueueItem, StartedCall, TextTurnResult, TranscriptTurn } from './types';
import { ApiError } from './errors';
import { logRenewalEvent, seedRenewalCase } from './mock';

const delay = (ms = 120) => new Promise((r) => setTimeout(r, ms));
const day = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

const QUEUE: QueueItem[] = [
  {
    policyId: 'LL-MOT-20418', holderName: 'Sample: Meera Iyer', product: 'Motor comprehensive', expiresOn: day(9), daysToExpiry: 9, score: 0.34,
    signals: [{ code: 'CLAIM_FREE_3Y', label: 'Claim-free for 3 years', severity: 'LOW', weight: 0.1 }, { code: 'LATE_RENEWER', label: 'Renewed late last year', severity: 'MEDIUM', weight: 0.24 }],
    route: 'AGENT_CALL',
  },
  {
    policyId: 'LL-HLT-11873', holderName: 'Sample: Arjun Nair', product: 'Health floater', expiresOn: day(14), daysToExpiry: 14, score: 0.58,
    signals: [{ code: 'PREMIUM_JUMP', label: 'Premium up 18%', severity: 'MEDIUM', weight: 0.3 }, { code: 'ADDON_DROP_HISTORY', label: 'Dropped an add-on last time', severity: 'LOW', weight: 0.15 }],
    route: 'AGENT_CALL',
  },
  {
    policyId: 'LL-MOT-20977', holderName: 'Sample: Kavita Rao', product: 'Motor third party', expiresOn: day(3), daysToExpiry: 3, score: 0.86,
    signals: [{ code: 'OPEN_CLAIM', label: 'Open claim on this policy', severity: 'HIGH', weight: 0.5 }, { code: 'DISPUTE', label: 'Premium dispute logged', severity: 'HIGH', weight: 0.36 }],
    route: 'HUMAN_ONLY',
  },
  {
    policyId: 'LL-TRV-30211', holderName: 'Sample: Imran Sheikh', product: 'Travel annual', expiresOn: day(21), daysToExpiry: 21, score: 0.12,
    signals: [{ code: 'DND', label: 'Do-not-call registered', severity: 'LOW', weight: 0.12 }],
    route: 'REMINDER_SMS',
  },
  {
    policyId: 'LL-HLT-11990', holderName: 'Sample: Sunita Menon', product: 'Health individual', expiresOn: day(6), daysToExpiry: 6, score: 0.47,
    signals: [{ code: 'AGE_BAND_CHANGE', label: 'Moves to next age band', severity: 'MEDIUM', weight: 0.25 }],
    route: 'AGENT_CALL',
  },
];

interface MockCall {
  view: CallView;
  turns: number;
}
const calls = new Map<string, MockCall>();

function turn(role: string, text: string): TranscriptTurn {
  return { role, text, at: new Date().toISOString() };
}

function build(callId: string, policyId: string, holderName: string): MockCall {
  const greeting = `Hello, this is the Lotusleaf General Insurance renewal assistant, an AI agent. This call may be recorded. Am I speaking with ${holderName.replace('Sample: ', '')}?`;
  const view: CallView = {
    callId, caseId: callId, policyId, holderName, greeting,
    identityVerified: false, verifyFailures: 0, outOfPlaybookRequests: 0, mustHandoff: false, outcome: null,
    lastQuote: null, paymentLinkSent: false, handoffReason: null, callbackAt: null,
    transcript: [turn(CallTurnRole.AGENT, greeting)], summary: [],
  };
  seedRenewalCase(callId, `Sample: renewal call for ${policyId}`);
  logRenewalEvent(callId, 'AGENT_GREETED', { disclosure: 'ai_and_recording' });
  return { view, turns: 0 };
}

function ensure(callId: string): MockCall {
  let c = calls.get(callId);
  if (!c) {
    const item = QUEUE[0];
    c = build(callId, item.policyId, item.holderName);
    calls.set(callId, c);
  }
  return c;
}

export const mockRenewals = {
  async getQueue(): Promise<QueueItem[]> {
    await delay();
    return structuredClone(QUEUE);
  },

  async startCall(policyId: string): Promise<StartedCall> {
    await delay();
    const item = QUEUE.find((q) => q.policyId === policyId);
    if (item && item.route !== RenewalRoute.AGENT_CALL) {
      throw new ApiError({ status: 409, title: 'Conflict', detail: item.route === RenewalRoute.HUMAN_ONLY ? RenewalRoute.HUMAN_ONLY : 'DO_NOT_CALL' });
    }
    const callId = `sample-call-${policyId.toLowerCase()}`;
    const call = build(callId, policyId, item?.holderName ?? 'Sample: Meera Iyer');
    calls.set(callId, call);
    return { callId, caseId: callId, greeting: call.view.greeting };
  },

  async getCall(callId: string): Promise<CallView> {
    await delay(60);
    return structuredClone(ensure(callId).view);
  },

  async endCall(callId: string): Promise<{ outcome: CallOutcome }> {
    await delay();
    const c = ensure(callId);
    const v = c.view;
    const outcome: CallOutcome = v.mustHandoff ? CallOutcome.HANDED_OFF : v.paymentLinkSent ? CallOutcome.RENEWAL_PENDING_PAYMENT : CallOutcome.NO_DECISION;
    v.outcome = outcome;
    if (outcome === CallOutcome.RENEWAL_PENDING_PAYMENT) {
      v.summary = [
        { statement: 'Customer confirmed identity with date of birth.', quote: '12 March 1984' },
        { statement: 'Customer dropped roadside assistance and chose quarterly payment.', quote: 'Drop roadside assistance and pay quarterly' },
        { statement: 'Payment link sent to the mobile number on file.', quote: 'I have sent the link ending 4417' },
      ];
    } else if (outcome === CallOutcome.HANDED_OFF) {
      v.summary = [{ statement: 'Agent handed the call to a person.', quote: v.handoffReason ?? 'Handing you to a colleague' }];
    }
    logRenewalEvent(callId, 'CALL_ENDED', { outcome });
    return { outcome };
  },

  async textCall(callId: string): Promise<{ greeting: string }> {
    await delay(60);
    return { greeting: ensure(callId).view.greeting };
  },

  async textTurn(callId: string, text: string): Promise<TextTurnResult> {
    await delay();
    const c = ensure(callId);
    const v = c.view;
    c.turns += 1;
    v.transcript.push(turn(CallTurnRole.USER, text));
    let reply: string;
    const toolCalls: TextTurnResult['toolCalls'] = [];
    if (/\b(50|40|30)\s*%/.test(text)) {
      v.outOfPlaybookRequests += 1;
      reply = 'I can only offer the discount in the approved range, and the system refused that one. I can note your request for a colleague.';
      toolCalls.push({ name: 'quote', args: { discountPercent: 50 }, result: { refused: true } });
    } else if (!v.identityVerified && c.turns === 1) {
      reply = 'Thanks. Before I discuss the policy, may I have your date of birth?';
    } else if (!v.identityVerified) {
      v.identityVerified = true;
      reply = 'Thank you, you are verified. Your renewal premium is ₹18,420. You can drop add-ons or pay in instalments.';
      toolCalls.push({ name: 'verify_identity', args: {}, result: { verified: true } });
    } else {
      v.lastQuote = { quoteId: 'sample-quote-1', annualPremium: 17_380, instalments: 4, perInstalment: 4_345 };
      v.paymentLinkSent = true;
      reply = 'Done. Without roadside assistance it is ₹17,380 a year, or ₹4,345 a quarter. I have sent the payment link to the number ending 4417.';
      toolCalls.push({ name: 'quote', args: { dropAddons: ['ROADSIDE'], paymentPlan: 'QUARTERLY' }, result: v.lastQuote });
      toolCalls.push({ name: 'send_payment_link', args: {}, result: { sent: true } });
    }
    v.transcript.push(turn(CallTurnRole.AGENT, reply));
    logRenewalEvent(callId, 'TURN', { user: text, tools: toolCalls.map((t) => t.name) });
    return { reply, toolCalls };
  },
};
