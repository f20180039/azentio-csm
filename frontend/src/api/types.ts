import { CallOutcome, CaseStatus, FindingStatus, RenewalRoute, Role } from '../vocab';

export { CallOutcome, CaseStatus, FindingStatus, RenewalRoute, Role };

export const CASE_STATUSES: CaseStatus[] = Object.values(CaseStatus);

export type Severity = 'LOW' | 'MEDIUM' | 'HIGH';
export type FindingSource = 'RULE' | 'MODEL' | 'LLM' | 'SECURITY';

export interface CaseSummary {
  id: string;
  caseType: string;
  title: string;
  /** Facts sent with the upload (policy number, declared income, deadline); rules read them. */
  attributes?: Record<string, unknown>;
  status: CaseStatus;
  riskScore: number | null;
  amountAtRisk: number | null;
  findingsCount: number;
  createdBy?: string;
  createdAt: string;
  updatedAt?: string;
}

export interface DocumentInfo {
  id: string;
  filename: string;
  mimeType?: string;
  sha256: string;
  sizeBytes?: number;
  pageCount?: number | null;
}

export interface Evidence {
  documentId?: string;
  page: number;
  quote: string;
}

export interface Finding {
  id: string;
  ruleId: string;
  title: string;
  detail?: string;
  severity: Severity;
  weight: number;
  amount?: number | null;
  source: FindingSource;
  evidence: Evidence[];
  llmNote?: string | null;
  verified?: boolean | null;
  status: FindingStatus;
  decidedBy?: string | null;
  decisionReason?: string | null;
  decidedAt?: string | null;
}

export interface HiddenText {
  page: number;
  text: string;
  reason: string;
}

export interface SecuritySummary {
  hidden_text?: HiddenText[];
  injection?: { suspected: boolean; score: number; matches: string[] };
  pii?: { masked: Record<string, number> };
}

export interface ExtractionSummary {
  documentId?: string;
  modelProvider?: string;
  modelName?: string;
  promptVersion?: string;
  security?: SecuritySummary;
}

export interface CaseDetail extends CaseSummary {
  pipelineVersion?: string;
  documents: DocumentInfo[];
  findings: Finding[];
  extraction?: ExtractionSummary | null;
  extractions?: ExtractionSummary[];
}

export interface PageText {
  page: number;
  text: string;
}

export interface AuditEvent {
  id: number;
  caseId?: string | null;
  actor: string;
  action: string;
  payload?: unknown;
  prevHash?: string;
  hash?: string;
  createdAt: string;
}

export interface AuditVerifyResult {
  valid: boolean;
  checked?: number;
  brokenAt?: number | null;
  detail?: string;
}

export interface PackRule {
  id: string;
  weight: number;
  rationale?: string;
  params?: Record<string, unknown>;
}

export interface RulePackInfo {
  caseType: string;
  label?: string;
  extractionSchema?: string;
  routing?: { autoClearBelow: number; escalateAtOrAbove: number };
  rules: PackRule[];
}

export interface Stats {
  byStatus?: Partial<Record<CaseStatus, number>>;
  jobsPending?: number;
  p50Ms?: number | null;
  p95Ms?: number | null;
  cacheHits?: number;
}

export interface UploadResult {
  case: CaseSummary;
  cache: 'HIT' | 'MISS';
}

export type FindingAction = 'ACCEPT' | 'DISMISS' | 'EDIT';
export type CaseAction = 'APPROVE' | 'REJECT' | 'ESCALATE';

export interface Page<T> {
  items: T[];
  total: number;
}

/* ---------- renewals (Renewal Desk voice agent) ---------- */

export interface RenewalSignal {
  code: string;
  label: string;
  severity: Severity;
  weight: number;
}

export interface QueueItem {
  policyId: string;
  holderName: string;
  product: string;
  expiresOn: string;
  daysToExpiry: number;
  score: number;
  signals: RenewalSignal[];
  route: RenewalRoute;
}

export interface StartedCall {
  callId: string;
  caseId: string;
  greeting: string;
}

export interface TranscriptTurn {
  role: string;
  text: string;
  at?: string;
}

export interface SummaryItem {
  statement: string;
  quote: string;
}

export interface CallQuote {
  quoteId?: string;
  annualPremium?: number;
  instalments?: number;
  perInstalment?: number;
}

export interface CallView {
  callId: string;
  caseId: string;
  policyId: string;
  holderName: string;
  greeting: string;
  identityVerified: boolean;
  verifyFailures: number;
  outOfPlaybookRequests: number;
  mustHandoff: boolean;
  outcome: CallOutcome | null;
  lastQuote: CallQuote | null;
  paymentLinkSent: boolean;
  handoffReason: string | null;
  callbackAt: string | null;
  transcript: TranscriptTurn[];
  summary: SummaryItem[];
}

export interface TextTurnResult {
  reply: string;
  toolCalls: { name: string; args: unknown; result: unknown }[];
}
