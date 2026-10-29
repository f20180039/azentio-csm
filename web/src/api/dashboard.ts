import { get, MOCK_MODE } from './client';
import { sampleDashboard } from './mock';
import type { CallOutcome } from './types';

export interface DashboardKpis {
  callsToday: number;
  callsTotal: number;
  inProgress: number;
  renewed: number;
  handedOff: number;
  noDecision: number;
  premiumRetained: number;
  premiumAtRisk: number;
  blockedRequests: number;
  refusals: number;
  identityFailures: number;
  /** 0..1 */
  saveRate: number;
}

export interface DayOutcomes {
  day: string;
  renewed: number;
  handedOff: number;
  noDecision: number;
}

export interface RecentCall {
  callId: string;
  holderName: string;
  policyId: string;
  product: string;
  startedAt: string;
  endedAt: string | null;
  outcome: CallOutcome | null;
  mustHandoff: boolean;
  outOfPlaybookRequests: number;
}

export type GuardrailAction = 'rule.outside_playbook' | 'tool.refused' | 'identity.failed' | 'tool.handoff_to_human';

export interface GuardrailEvent {
  at: string;
  callId: string;
  holderName: string;
  action: GuardrailAction;
  detail: string;
}

export interface RiskBand {
  band: string;
  count: number;
  agentCall: number;
  humanOnly: number;
  reminderSms: number;
}

export interface Dashboard {
  kpis: DashboardKpis;
  outcomesByDay: DayOutcomes[];
  recentCalls: RecentCall[];
  guardrailEvents: GuardrailEvent[];
  riskBands: RiskBand[];
}

export async function getDashboard(): Promise<Dashboard> {
  if (MOCK_MODE) return sampleDashboard();
  const d = await get<Dashboard>('/renewals/dashboard');
  return {
    ...d,
    outcomesByDay: d.outcomesByDay ?? [],
    recentCalls: d.recentCalls ?? [],
    guardrailEvents: d.guardrailEvents ?? [],
    riskBands: d.riskBands ?? [],
  };
}
