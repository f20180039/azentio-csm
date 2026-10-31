/* Fixed vocabularies, defined once. Values follow docs/superpowers/plans/2026-10-31-csm-voice-agent.md. */

type ValueOf<T> = T[keyof T];

/* ---------- support desk (voice service + system of record) ---------- */

export const SupportOutcome = {
  RESOLVED: 'RESOLVED',
  TICKET_CREATED: 'TICKET_CREATED',
  COMPLAINT_REGISTERED: 'COMPLAINT_REGISTERED',
  ROUTED: 'ROUTED',
  ESCALATED: 'ESCALATED',
  ABANDONED: 'ABANDONED',
} as const;
export type SupportOutcome = ValueOf<typeof SupportOutcome>;

export const SupportChannel = { VOICE: 'VOICE', SIM_AUDIO: 'SIM_AUDIO', TEXT: 'TEXT', PHONE: 'PHONE' } as const;
export type SupportChannel = ValueOf<typeof SupportChannel>;

export const TurnRole = { CUSTOMER: 'customer', AGENT: 'agent' } as const;
export type TurnRole = ValueOf<typeof TurnRole>;

/** backend/voice/app/intents.py Intent. */
export const Intent = {
  LOAN_APPLICATION: 'LOAN_APPLICATION',
  REPAYMENT: 'REPAYMENT',
  ACCOUNT: 'ACCOUNT',
  SERVICE_REQUEST: 'SERVICE_REQUEST',
  PRODUCT_INFO: 'PRODUCT_INFO',
  COMPLAINT: 'COMPLAINT',
  INSURANCE: 'INSURANCE',
  IDENTITY: 'IDENTITY',
  HUMAN_AGENT: 'HUMAN_AGENT',
  UNSUPPORTED: 'UNSUPPORTED',
  UNCLEAR: 'UNCLEAR',
  CHITCHAT: 'CHITCHAT',
} as const;
export type Intent = ValueOf<typeof Intent>;

/** Labels outside the voice service's Intent set that the desk still gives a friendly name. */
export const LegacyIntent = {
  TRANSACTION: 'TRANSACTION',
  SERVICE_REQUEST_STATUS: 'SERVICE_REQUEST_STATUS',
  PRODUCT_QUESTION: 'PRODUCT_QUESTION',
  FAQ: 'FAQ',
  STATEMENT: 'STATEMENT',
  ESCALATION: 'ESCALATION',
  GREETING: 'GREETING',
} as const;
export type LegacyIntent = ValueOf<typeof LegacyIntent>;

/** How a turn's intent was identified (meta.intent_source from the voice service). */
export const IntentSource = { LLM: 'llm', RULES: 'rules' } as const;
export type IntentSource = ValueOf<typeof IntentSource>;

export const Verification = { NOT_VERIFIED: 'NOT_VERIFIED', VERIFIED: 'VERIFIED', LOCKED: 'LOCKED' } as const;
export type Verification = ValueOf<typeof Verification>;

/** Bank simulator /ops/records?kind= */
export const RecordKind = { TICKET: 'ticket', COMPLAINT: 'complaint', ROUTED: 'routed', ESCALATION: 'escalation' } as const;
export type RecordKind = ValueOf<typeof RecordKind>;

/* ---------- renewal desk ---------- */

export const CallOutcome = {
  HANDED_OFF: 'HANDED_OFF',
  RENEWAL_PENDING_PAYMENT: 'RENEWAL_PENDING_PAYMENT',
  NO_DECISION: 'NO_DECISION',
} as const;
export type CallOutcome = ValueOf<typeof CallOutcome>;

export const RenewalRoute = { AGENT_CALL: 'AGENT_CALL', HUMAN_ONLY: 'HUMAN_ONLY', REMINDER_SMS: 'REMINDER_SMS' } as const;
export type RenewalRoute = ValueOf<typeof RenewalRoute>;

/** Speaker of a renewal-call transcript line. */
export const CallTurnRole = { AGENT: 'agent', USER: 'user' } as const;
export type CallTurnRole = ValueOf<typeof CallTurnRole>;

/** Simulated-caller persona keys, as written by backend/voice/eval/personas.py. */
export const Persona = {
  AGREEABLE: 'agreeable',
  PRICE_SENSITIVE: 'price_sensitive',
  DISCOUNT_PUSHER: 'discount_pusher',
  WRONG_DOB: 'wrong_dob',
  SKIP_IDENTITY: 'skip_identity',
  BEREAVED: 'bereaved',
} as const;
export type Persona = ValueOf<typeof Persona>;

/* ---------- cases ---------- */

export const CaseStatus = {
  RECEIVED: 'RECEIVED',
  PROCESSING: 'PROCESSING',
  NEEDS_REVIEW: 'NEEDS_REVIEW',
  AUTO_CLEARED: 'AUTO_CLEARED',
  ESCALATED: 'ESCALATED',
  APPROVED: 'APPROVED',
  REJECTED: 'REJECTED',
  FAILED: 'FAILED',
} as const;
export type CaseStatus = ValueOf<typeof CaseStatus>;

export const FindingStatus = { OPEN: 'OPEN', ACCEPTED: 'ACCEPTED', DISMISSED: 'DISMISSED', EDITED: 'EDITED' } as const;
export type FindingStatus = ValueOf<typeof FindingStatus>;

export const Role = { ANALYST: 'ANALYST', REVIEWER: 'REVIEWER', ADMIN: 'ADMIN' } as const;
export type Role = ValueOf<typeof Role>;

/* ---------- UI ---------- */

export const Theme = { LIGHT: 'light', DARK: 'dark' } as const;
export type Theme = ValueOf<typeof Theme>;

export const StorageKey = { THEME: 'ci-theme', SESSION: 'azentio-csm-session' } as const;
export type StorageKey = ValueOf<typeof StorageKey>;
