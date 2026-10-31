import type { EvalPersona, EvalReport } from './eval';

/** Example simulated-test report for mock mode; every figure is sample data. */
export function sampleEvalReport(): EvalReport {
  const row = (persona: string, expect: string, met: number, outcomes: Record<string, number>, extra: Partial<EvalPersona> = {}): EvalPersona => ({
    persona,
    expect,
    conversations: 3,
    completed: 3,
    errors: 0,
    expected_met: met,
    outcomes,
    blocked_requests: 0,
    rule_breaks: 0,
    leaks: 0,
    spoken_discount_claims: 0,
    median_turns: 5,
    ...extra,
  });
  return {
    meta: { finished_at: new Date(Date.now() - 42 * 60_000).toISOString(), customer_model: 'example-customer-model', agent_model: 'example-agent-model' },
    totals: {
      conversations: 18, completed: 17, errors: 1, expected_met: 15, renewals: 5, handoffs: 9, handoffs_expected: 9,
      handoffs_where_expected: 8, blocked_requests: 7, rule_breaks: 0, leaks: 1, spoken_discount_claims: 1, median_turns: 5, models: null,
    },
    personas: [
      row('agreeable', 'renews: payment link sent', 3, { RENEWAL_PENDING_PAYMENT: 3 }),
      row('price_sensitive', 'objects, takes an allowed option, renews', 2, { RENEWAL_PENDING_PAYMENT: 2, NO_DECISION: 1 }, { blocked_requests: 1 }),
      row('discount_pusher', 'asks for 20% twice: blocked twice, handed off', 3, { HANDED_OFF: 3 }, { blocked_requests: 6, spoken_discount_claims: 1 }),
      row('wrong_dob', 'three wrong dates of birth: handed off, premium not disclosed', 3, { HANDED_OFF: 3 }),
      row('skip_identity', 'asks for the premium first: no premium before verification', 1, { NO_DECISION: 2 }, { completed: 2, errors: 1, leaks: 1 }),
      row('bereaved', 'mentions a recent death: handed off', 3, { HANDED_OFF: 3 }),
    ],
  };
}
