import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import type { AuditEvent, AuditVerifyResult, CaseAction, CaseDetail, Finding, PageText, SecuritySummary } from '../api/types';
import { evidenceKey, FindingCard } from '../components/FindingCard';
import { HighlightedText, type Highlight } from '../components/HighlightedText';
import { ScoreBar, StatusPill } from '../components/StatusPill';
import { useToast } from '../components/Toasts';
import { formatDateTime, formatInr, humanise } from '../format';
import { useSession } from '../session';

type Tab = 'findings' | 'audit';

function collectSecurity(c: CaseDetail): SecuritySummary {
  const all = [c.extraction, ...(c.extractions ?? [])].filter(Boolean).map((e) => e!.security ?? {});
  return {
    hidden_text: all.flatMap((s) => s.hidden_text ?? []),
    injection: all.map((s) => s.injection).find((i) => i?.suspected) ?? all[0]?.injection,
    pii: all[0]?.pii,
  };
}

export function CaseWorkspace() {
  const { id = '' } = useParams();
  const { can } = useSession();
  const toast = useToast();
  const [kase, setKase] = useState<CaseDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [tab, setTab] = useState<Tab>('findings');
  const [docId, setDocId] = useState<string | null>(null);
  const [pages, setPages] = useState<PageText[] | null>(null);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [pendingScroll, setPendingScroll] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const c = await api.getCase(id);
      setKase(c);
      setDocId((d) => d ?? c.documents[0]?.id ?? null);
    } catch (e) {
      setNotFound(true);
      toast.error(e);
    }
  }, [id, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const processing = kase?.status === 'PROCESSING' || kase?.status === 'RECEIVED';
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [processing, load]);

  useEffect(() => {
    if (!docId) return;
    setPages(null);
    api.getPages(id, docId).then(setPages).catch((e) => {
      toast.error(e);
      setPages([]);
    });
  }, [id, docId, toast]);

  const highlightsByPage = useMemo(() => {
    const map = new Map<number, Highlight[]>();
    if (!kase || !docId) return map;
    const firstDoc = kase.documents[0]?.id;
    kase.findings.forEach((f) =>
      f.evidence.forEach((ev, i) => {
        if ((ev.documentId ?? firstDoc) !== docId) return;
        const list = map.get(ev.page) ?? [];
        list.push({ key: evidenceKey(f.id, i), quote: ev.quote });
        map.set(ev.page, list);
      }),
    );
    return map;
  }, [kase, docId]);

  useEffect(() => {
    if (!pendingScroll || !pages) return;
    const el = document.getElementById(`ev-${pendingScroll}`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
      toast.push('Quote not found in this page text', 'The evidence may refer to text that was masked or hidden.', 'warn');
    }
    setPendingScroll(null);
  }, [pendingScroll, pages, toast]);

  function showEvidence(key: string, documentId: string | undefined) {
    setTab('findings');
    setActiveKey(key);
    const target = documentId ?? kase?.documents[0]?.id ?? null;
    if (target && target !== docId) setDocId(target);
    setPendingScroll(key);
  }

  function onFindingDecided(f: Finding) {
    setKase((k) => (k ? { ...k, findings: k.findings.map((x) => (x.id === f.id ? f : x)) } : k));
  }

  if (notFound) {
    return (
      <div className="empty">
        <strong>This case could not be loaded</strong>
        <Link to="/">Back to the queue</Link>
      </div>
    );
  }
  if (!kase) return <p className="muted">Loading case…</p>;

  const security = collectSecurity(kase);
  const hidden = security.hidden_text ?? [];
  const injection = security.injection?.suspected ? security.injection : null;
  const piiTotal = Object.values(security.pii?.masked ?? {}).reduce((a, b) => a + b, 0);
  const open = kase.findings.filter((f) => f.status === 'OPEN').length;
  const findings = [...kase.findings].sort((a, b) => sevRank(b) - sevRank(a) || (b.amount ?? 0) - (a.amount ?? 0));

  return (
    <>
      <div className="case-head">
        <Link to="/" className="small">
          ← Queue
        </Link>
        <div className="page-head">
          <div style={{ display: 'grid', gap: 6 }}>
            <h1>{kase.title}</h1>
            <div className="case-meta">
              <StatusPill status={kase.status} />
              <span className="mono small">{kase.caseType}</span>
              <span>
                Risk <ScoreBar score={kase.riskScore} />
              </span>
              <span>
                At risk <span className="num">{formatInr(kase.amountAtRisk)}</span>
              </span>
              <span className="muted small">
                {kase.findings.length} findings · {open} open
              </span>
              {kase.createdBy && <span className="muted small">uploaded by {kase.createdBy}</span>}
            </div>
            {kase.attributes && Object.keys(kase.attributes).length > 0 && (
              <dl className="case-meta small" aria-label="Case details">
                {Object.entries(kase.attributes).map(([k, v]) => (
                  <div key={k}>
                    <dt className="muted" style={{ display: 'inline' }}>{k}</dt>{' '}
                    <dd className="mono" style={{ display: 'inline', margin: 0 }}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
          <CaseActions kase={kase} canDecide={can('REVIEWER')} onDone={load} />
        </div>
      </div>

      {(hidden.length > 0 || injection) && (
        <div className="banner bad" role="alert">
          <strong>Possible document manipulation</strong>
          {hidden.length > 0 && (
            <span>
              {hidden.length} hidden text span{hidden.length > 1 ? 's' : ''} found ({[...new Set(hidden.map((h) => humanise(h.reason)))].join(', ')}). Hidden
              text was kept out of every model prompt.
            </span>
          )}
          {injection && (
            <span>
              Instructions aimed at the AI were detected (score <span className="num">{injection.score.toFixed(2)}</span>):{' '}
              {injection.matches.map((m) => `“${m}”`).join(', ')}. The verdict comes from the rules, not from the document.
            </span>
          )}
        </div>
      )}

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'findings'} onClick={() => setTab('findings')}>
          Findings &amp; evidence
        </button>
        <button role="tab" aria-selected={tab === 'audit'} onClick={() => setTab('audit')}>
          Audit trail
        </button>
      </div>

      {tab === 'findings' ? (
        <div className="workspace">
          <div className="findings">
            {processing && <div className="banner info">Extraction and scoring are running. This page refreshes on its own.</div>}
            {kase.status === 'FAILED' && <div className="banner bad">Processing failed after retries. Check the audit trail for the error.</div>}
            {!processing && findings.length === 0 && (
              <div className="panel empty">
                <strong>No findings</strong>
                <span>No rule in this pack fired for these documents.</span>
              </div>
            )}
            {findings.map((f) => (
              <FindingCard key={f.id} caseId={kase.id} finding={f} canDecide={can('REVIEWER')} onDecided={onFindingDecided} onShowEvidence={showEvidence} />
            ))}
          </div>

          <aside className="doc-pane" aria-label="Source document">
            <div className="panel">
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span className="label">Source text</span>
                {piiTotal > 0 && <span className="pill neutral">{piiTotal} personal identifiers masked</span>}
              </div>
              {kase.documents.length > 1 ? (
                <select aria-label="Document" value={docId ?? ''} onChange={(e) => setDocId(e.target.value)}>
                  {kase.documents.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.filename}
                    </option>
                  ))}
                </select>
              ) : (
                kase.documents[0] && <span className="mono small">{kase.documents[0].filename}</span>
              )}
              <div className="doc-pages">
                {pages === null && <span className="muted small">Loading pages…</span>}
                {pages?.length === 0 && <span className="muted small">No text available for this document yet.</span>}
                {pages?.map((p) => (
                  <div className="doc-page" key={p.page}>
                    <span className="label">Page {p.page}</span>
                    <HighlightedText text={p.text} highlights={highlightsByPage.get(p.page) ?? []} activeKey={activeKey} idPrefix="ev" />
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </div>
      ) : (
        <AuditTab caseId={kase.id} canVerify={can('ADMIN')} />
      )}
    </>
  );
}

function sevRank(f: Finding) {
  return f.severity === 'HIGH' ? 3 : f.severity === 'MEDIUM' ? 2 : 1;
}

export function CaseActions({ kase, canDecide, onDone }: { kase: CaseDetail; canDecide: boolean; onDone: () => void }) {
  const [action, setAction] = useState<CaseAction | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const final = kase.status === 'APPROVED' || kase.status === 'REJECTED';

  if (!canDecide) return <span className="small muted">Read-only: reviewers decide cases</span>;
  if (final || kase.status === 'PROCESSING' || kase.status === 'RECEIVED') return null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!action || !reason.trim()) return;
    setBusy(true);
    try {
      await api.decideCase(kase.id, { action, reason: reason.trim() });
      toast.push(`Case ${action === 'APPROVE' ? 'approved' : action === 'REJECT' ? 'rejected' : 'escalated'}`, 'Recorded in the audit log.');
      setAction(null);
      setReason('');
      onDone();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  if (!action) {
    return (
      <div className="case-actions">
        <button className="btn primary" onClick={() => setAction('APPROVE')}>
          Approve
        </button>
        <button className="btn danger" onClick={() => setAction('REJECT')}>
          Reject
        </button>
        {kase.status !== 'ESCALATED' && (
          <button className="btn" onClick={() => setAction('ESCALATE')}>
            Escalate
          </button>
        )}
      </div>
    );
  }
  return (
    <form className="case-actions" onSubmit={submit} style={{ alignItems: 'end' }}>
      <div className="field" style={{ minWidth: 260 }}>
        <label htmlFor="case-reason">Reason to {action.toLowerCase()}</label>
        <input id="case-reason" type="text" value={reason} onChange={(e) => setReason(e.target.value)} required autoFocus />
      </div>
      <button type="submit" className={`btn ${action === 'REJECT' ? 'danger' : 'primary'}`} disabled={busy || !reason.trim()}>
        {humanise(action)}
      </button>
      <button type="button" className="btn ghost" onClick={() => setAction(null)}>
        Cancel
      </button>
    </form>
  );
}

export function AuditTab({ caseId, canVerify }: { caseId: string; canVerify: boolean }) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [verify, setVerify] = useState<AuditVerifyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  useEffect(() => {
    api.getAudit(caseId).then(setEvents).catch((e) => {
      toast.error(e);
      setEvents([]);
    });
  }, [caseId, toast]);

  async function runVerify() {
    setBusy(true);
    try {
      setVerify(await api.verifyAudit());
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel" style={{ padding: '12px 16px', display: 'grid', gap: 12 }}>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <p className="small muted">Append-only and hash-chained: each event's hash covers the previous one, so edits anywhere break the chain.</p>
        {canVerify && (
          <button className="btn sm" onClick={runVerify} disabled={busy}>
            {busy ? 'Verifying…' : 'Verify chain'}
          </button>
        )}
      </div>
      {verify && (
        <div className={`banner ${verify.valid ? 'info' : 'bad'}`} role="status">
          {verify.valid
            ? `Chain intact: ${verify.checked ?? 'all'} events verified.`
            : `Chain broken at event ${verify.brokenAt ?? '?'}. ${verify.detail ?? ''}`}
        </div>
      )}
      {events === null && <span className="muted small">Loading audit trail…</span>}
      {events?.length === 0 && <span className="muted small">No events recorded for this case.</span>}
      <div className="timeline">
        {events?.map((e) => (
          <div className="event" key={e.id}>
            <div style={{ display: 'grid', gap: 2 }}>
              <span className="num small">{formatDateTime(e.createdAt)}</span>
              <span className="small muted">{e.actor}</span>
            </div>
            <div>
              <strong className="small">{humanise(e.action)}</strong>
              {e.payload != null && <pre>{JSON.stringify(e.payload, null, 1)}</pre>}
              {e.hash && <div className="hash">#{e.id} · {e.hash.slice(0, 16)}…</div>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
