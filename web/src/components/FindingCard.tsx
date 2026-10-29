import { useState, type FormEvent } from 'react';
import { api } from '../api/client';
import type { Finding, FindingAction } from '../api/types';
import { formatDateTime, formatInr } from '../format';
import { FindingStatusPill, SeverityPill } from './StatusPill';
import { useToast } from './Toasts';

export function evidenceKey(findingId: string, i: number) {
  return `${findingId}-e${i}`;
}

export function FindingCard({
  caseId,
  finding,
  canDecide,
  onDecided,
  onShowEvidence,
}: {
  caseId: string;
  finding: Finding;
  canDecide: boolean;
  onDecided: (f: Finding) => void;
  onShowEvidence: (key: string, documentId: string | undefined) => void;
}) {
  const [mode, setMode] = useState<FindingAction | null>(null);
  const [reason, setReason] = useState('');
  const [amount, setAmount] = useState(finding.amount?.toString() ?? '');
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const decided = finding.status !== 'OPEN';

  async function decide(action: FindingAction, e?: FormEvent) {
    e?.preventDefault();
    if (action !== 'ACCEPT' && !reason.trim()) return;
    setBusy(true);
    try {
      const updated = await api.decideFinding(caseId, finding.id, {
        action,
        reason: reason.trim() || undefined,
        amount: action === 'EDIT' && amount !== '' ? Number(amount) : undefined,
      });
      onDecided({ ...finding, ...updated });
      toast.push(action === 'ACCEPT' ? 'Finding accepted' : action === 'DISMISS' ? 'Finding dismissed' : 'Finding amount edited', 'Recorded in the audit log.');
      setMode(null);
      setReason('');
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className={`finding sev-${finding.severity} ${decided ? 'decided' : ''}`} aria-label={finding.title}>
      <div className="finding-top">
        <div style={{ display: 'grid', gap: 4 }}>
          <h3>{finding.title}</h3>
          <div className="finding-meta">
            <SeverityPill severity={finding.severity} />
            <span className="pill dim mono">{finding.ruleId}</span>
            <span className="small muted">
              weight <span className="num">{finding.weight.toFixed(2)}</span>
            </span>
            <span className="small muted">· {finding.source.toLowerCase()}</span>
          </div>
        </div>
        <div style={{ textAlign: 'right', display: 'grid', gap: 4, justifyItems: 'end' }}>
          <span className="num" style={{ fontWeight: 500 }}>
            {finding.amount != null ? formatInr(finding.amount) : ''}
          </span>
          <FindingStatusPill status={finding.status} />
        </div>
      </div>

      {finding.detail && <p className="small">{finding.detail}</p>}

      {finding.llmNote && (
        <div className="llm-note">
          <div className="row">
            <span className="label">Model explanation</span>
            {finding.verified ? (
              <span className="pill ok" title="Every quote in this note was found verbatim in the source text">
                Quote verified
              </span>
            ) : (
              <span className="pill warn" title="The quote could not be matched to the source text">
                Unverified
              </span>
            )}
          </div>
          <p>{finding.llmNote}</p>
        </div>
      )}

      {finding.evidence.length > 0 && (
        <div className="evidence-links">
          {finding.evidence.map((ev, i) => (
            <button
              key={i}
              type="button"
              className="evidence-link"
              onClick={() => onShowEvidence(evidenceKey(finding.id, i), ev.documentId)}
              title={ev.quote}
            >
              Evidence {i + 1} · p.{ev.page}
            </button>
          ))}
        </div>
      )}

      {decided && (
        <p className="decision-note">
          {finding.decidedBy ? `${finding.decidedBy}` : 'Decided'}
          {finding.decidedAt ? ` · ${formatDateTime(finding.decidedAt)}` : ''}
          {finding.decisionReason ? ` · “${finding.decisionReason}”` : ''}
        </p>
      )}

      {!decided && canDecide && mode === null && (
        <div className="row">
          <button className="btn primary sm" disabled={busy} onClick={() => decide('ACCEPT')}>
            Accept
          </button>
          <button className="btn sm" onClick={() => setMode('EDIT')}>
            Edit amount
          </button>
          <button className="btn sm danger" onClick={() => setMode('DISMISS')}>
            Dismiss
          </button>
        </div>
      )}
      {!decided && !canDecide && <p className="small muted">Only reviewers can decide findings.</p>}

      {mode && (
        <form className="decide-form" onSubmit={(e) => decide(mode, e)}>
          {mode === 'EDIT' && (
            <div className="field">
              <label htmlFor={`amt-${finding.id}`}>Amount (₹)</label>
              <input id={`amt-${finding.id}`} type="number" min={0} step={1} value={amount} onChange={(e) => setAmount(e.target.value)} required />
            </div>
          )}
          <div className="field">
            <label htmlFor={`reason-${finding.id}`}>Reason (required)</label>
            <textarea
              id={`reason-${finding.id}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={mode === 'DISMISS' ? 'e.g. Reversal is a refund from the same merchant' : 'e.g. Only one ICU day is unsupported'}
              required
            />
          </div>
          <div className="row">
            <button type="submit" className={`btn sm ${mode === 'DISMISS' ? 'danger' : 'primary'}`} disabled={busy || !reason.trim()}>
              {mode === 'DISMISS' ? 'Dismiss finding' : 'Save amount'}
            </button>
            <button type="button" className="btn ghost sm" onClick={() => setMode(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </article>
  );
}
