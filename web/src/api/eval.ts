import { MOCK_MODE } from './client';
import { ApiError } from './errors';
import { VOICE_BASE } from './renewals';

export interface EvalTotals {
  conversations: number;
  completed: number;
  errors: number;
  expected_met: number;
  renewals: number;
  handoffs: number;
  handoffs_expected: number;
  handoffs_where_expected: number;
  blocked_requests: number;
  rule_breaks: number;
  leaks: number;
  /** absent in reports written before the metric existed */
  spoken_discount_claims?: number;
  median_turns: number | null;
}

export interface EvalPersona {
  persona: string;
  expect: string;
  conversations: number;
  completed: number;
  errors: number;
  expected_met: number;
  outcomes: Record<string, number>;
  blocked_requests: number;
  rule_breaks: number;
  leaks: number;
  spoken_discount_claims?: number;
  median_turns: number | null;
}

export interface EvalReport {
  meta: { started_at?: string; finished_at?: string; customer_model?: string; agent_model?: string; partial?: string };
  totals: EvalTotals;
  personas: EvalPersona[];
}

/** The latest simulated-customer run from the voice service, or null when none has been run. */
export async function getEvalLatest(): Promise<EvalReport | null> {
  if (MOCK_MODE) return null;
  let res: Response;
  try {
    res = await fetch(`${VOICE_BASE}/v1/eval/latest`);
  } catch {
    throw new ApiError({ status: 0, title: 'Cannot reach the voice service', detail: `Check that it is running at ${VOICE_BASE}.` });
  }
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError({ status: res.status, title: 'Simulated test results could not be loaded' });
  return (await res.json()) as EvalReport;
}
