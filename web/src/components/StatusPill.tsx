import type { CaseStatus, FindingStatus, Severity } from '../api/types';
import { humanise } from '../format';

const CASE_TONE: Record<CaseStatus, string> = {
  RECEIVED: 'dim',
  PROCESSING: 'info pulse',
  NEEDS_REVIEW: 'warn',
  AUTO_CLEARED: 'ok',
  ESCALATED: 'bad',
  APPROVED: 'ok',
  REJECTED: 'bad',
  FAILED: 'bad',
};

export function StatusPill({ status }: { status: CaseStatus }) {
  return (
    <span className={`pill ${CASE_TONE[status] ?? 'dim'}`}>
      <span className="dot" aria-hidden="true" />
      {humanise(status)}
    </span>
  );
}

const SEV_TONE: Record<Severity, string> = { HIGH: 'bad', MEDIUM: 'warn', LOW: 'info' };
export function SeverityPill({ severity }: { severity: Severity }) {
  return <span className={`pill ${SEV_TONE[severity]}`}>{humanise(severity)}</span>;
}

const FINDING_TONE: Record<FindingStatus, string> = { OPEN: 'dim', ACCEPTED: 'ok', DISMISSED: 'dim', EDITED: 'neutral' };
export function FindingStatusPill({ status }: { status: FindingStatus }) {
  return <span className={`pill ${FINDING_TONE[status]}`}>{humanise(status)}</span>;
}

export function ScoreBar({ score }: { score: number | null }) {
  if (score == null) return <span className="muted">—</span>;
  const color = score >= 0.8 ? 'var(--bad)' : score >= 0.2 ? 'var(--warn)' : 'var(--ok)';
  return (
    <span className="score-bar" title={`Risk score ${score.toFixed(3)}`}>
      <span className="track" aria-hidden="true">
        <span className="fill" style={{ display: 'block', width: `${Math.min(100, score * 100)}%`, background: color }} />
      </span>
      <span className="num">{score.toFixed(2)}</span>
    </span>
  );
}
