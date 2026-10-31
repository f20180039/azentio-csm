import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  CHANNEL_LABEL,
  intentLabel,
  intentTone,
  listCalls,
  listRecords,
  OUTCOME_LABEL,
  OUTCOME_TONE,
  SUPPORT_OUTCOMES,
  RecordKind,
  type OpsRecord,
  type SupportCallSummary,
  type SupportOutcome,
} from '../api/support';
import { formatDateTime, humanise } from '../format';
import { Route } from '../routes';

const REFRESH_MS = 5000;

const RECORD_TABS: { kind: RecordKind; label: string; empty: string }[] = [
  { kind: RecordKind.TICKET, label: 'Tickets', empty: 'No service requests yet.' },
  { kind: RecordKind.COMPLAINT, label: 'Complaints', empty: 'No complaints registered yet.' },
  { kind: RecordKind.ROUTED, label: 'Routed queries', empty: 'No unsupported questions routed yet.' },
  { kind: RecordKind.ESCALATION, label: 'Escalations', empty: 'No calls escalated yet.' },
];

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function CallStatusPill({ c }: { c: Pick<SupportCallSummary, 'endedAt' | 'outcome'> }) {
  if (!c.endedAt) {
    return (
      <span className="pill info pulse">
        <span className="dot" aria-hidden="true" />
        Live
      </span>
    );
  }
  const o = c.outcome;
  return (
    <span className={`pill ${o ? OUTCOME_TONE[o] : 'dim'}`}>
      <span className="dot" aria-hidden="true" />
      {o ? OUTCOME_LABEL[o] : 'Ended'}
    </span>
  );
}

function CallsPanel() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<SupportOutcome | ''>('');
  const [calls, setCalls] = useState<SupportCallSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const filterRef = useRef(filter);
  filterRef.current = filter;

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setCalls(null);
    const wanted = filterRef.current;
    try {
      const items = await listCalls(wanted || undefined);
      if (filterRef.current !== wanted) return;
      setCalls(items);
      setError(null);
    } catch (e) {
      setError(errorText(e));
      setCalls((c) => c ?? []);
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(true), REFRESH_MS);
    return () => clearInterval(t);
  }, [load, filter]);

  const open = (id: string) => navigate(Route.supportCall(id));
  const onRowKey = (e: KeyboardEvent, id: string) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      open(id);
    }
  };

  return (
    <section className="panel" aria-labelledby="calls-title">
      <div className="sd-panel-head">
        <h2 id="calls-title">Calls</h2>
        <div className="filters" role="group" aria-label="Filter calls by outcome">
          {(['', ...SUPPORT_OUTCOMES] as const).map((o) => (
            <button
              key={o || 'all'}
              type="button"
              className={`chip${filter === o ? ' on' : ''}`}
              aria-pressed={filter === o}
              onClick={() => setFilter(o)}
            >
              {o ? OUTCOME_LABEL[o] : 'All'}
            </button>
          ))}
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Started</th>
              <th>Channel</th>
              <th>Verified</th>
              <th>Intents</th>
              <th className="r">Turns</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {calls === null && (
              <tr>
                <td colSpan={6} className="muted">
                  Loading calls…
                </td>
              </tr>
            )}
            {calls?.map((c) => (
              <tr key={c.id} className="clickable" tabIndex={0} onClick={() => open(c.id)} onKeyDown={(e) => onRowKey(e, c.id)} aria-label={`Open call started ${formatDateTime(c.startedAt)}`}>
                <td className="num">{formatDateTime(c.startedAt)}</td>
                <td>{CHANNEL_LABEL[c.channel] ?? humanise(c.channel)}</td>
                <td>{c.verified ? <span className="pill ok">Verified</span> : <span className="pill dim">Not verified</span>}</td>
                <td className="sd-wrap">
                  <div className="row" style={{ gap: 4 }}>
                    {c.intents.length === 0 && <span className="muted small">—</span>}
                    {c.intents.map((i) => (
                      <span key={i} className={`pill ${intentTone(i)}`} title={i}>
                        {intentLabel(i)}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="num r">{c.turnCount}</td>
                <td>
                  <CallStatusPill c={c} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && (
        <div className="empty" role="alert">
          <strong>Calls could not be loaded</strong>
          <span>{error}</span>
          <button className="btn" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}
      {calls?.length === 0 && !error && (
        <div className="empty">
          <strong>{filter ? `No calls with outcome “${OUTCOME_LABEL[filter]}”` : 'No calls yet'}</strong>
          <span>Start a call to talk to the agent or replay recorded audio.</span>
        </div>
      )}
    </section>
  );
}

function RecordsPanel() {
  const [kind, setKind] = useState<RecordKind>(RecordKind.TICKET);
  const [rows, setRows] = useState<OpsRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const kindRef = useRef(kind);
  kindRef.current = kind;
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const load = useCallback(async (quiet = false) => {
    const wanted = kindRef.current;
    if (!quiet) setRows(null);
    try {
      const items = await listRecords(wanted);
      if (kindRef.current !== wanted) return;
      setRows(items);
      setError(null);
    } catch (e) {
      if (kindRef.current !== wanted) return;
      setError(errorText(e));
      setRows((r) => r ?? []);
    }
  }, []);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(true), REFRESH_MS);
    return () => clearInterval(t);
  }, [load, kind]);

  const tab = RECORD_TABS.find((t) => t.kind === kind)!;
  const onTabKey = (e: KeyboardEvent, i: number) => {
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (!d) return;
    const next = (i + d + RECORD_TABS.length) % RECORD_TABS.length;
    setKind(RECORD_TABS[next].kind);
    tabRefs.current[next]?.focus();
  };

  return (
    <section className="panel" aria-labelledby="records-title">
      <div className="sd-panel-head">
        <h2 id="records-title">Bank records</h2>
        <span className="small muted">From the bank simulator, newest first</span>
      </div>
      <div className="tabs sd-tabs" role="tablist" aria-label="Record type">
        {RECORD_TABS.map((t, i) => (
          <button
            key={t.kind}
            ref={(el) => (tabRefs.current[i] = el)}
            role="tab"
            id={`rtab-${t.kind}`}
            aria-selected={kind === t.kind}
            aria-controls="records-panel"
            tabIndex={kind === t.kind ? 0 : -1}
            onClick={() => setKind(t.kind)}
            onKeyDown={(e) => onTabKey(e, i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div id="records-panel" role="tabpanel" aria-labelledby={`rtab-${kind}`} className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Reference</th>
              <th>Category</th>
              <th>Status</th>
              <th>Summary</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {rows === null && (
              <tr>
                <td colSpan={5} className="muted">
                  Loading {tab.label.toLowerCase()}…
                </td>
              </tr>
            )}
            {rows?.map((r) => (
              <tr key={r.ref}>
                <td>
                  <span className="ref-pill">{r.ref}</span>
                  {r.escalated && (
                    <span className="pill bad" style={{ marginLeft: 6 }}>
                      Escalated
                    </span>
                  )}
                </td>
                <td>{r.category ? <span title={r.category}>{humanise(r.category)}</span> : <span className="muted">—</span>}</td>
                <td>{r.status ? <span className="pill dim">{humanise(r.status)}</span> : <span className="muted">—</span>}</td>
                <td className="sd-wrap sd-summary">
                  {r.summary}
                  <div className="small muted">
                    {r.customer_ref && <span className="mono">{r.customer_ref}</span>}
                    {r.call_id && (
                      <>
                        {r.customer_ref && ' · '}
                        <Link to={Route.supportCall(r.call_id)}>Open call</Link>
                      </>
                    )}
                  </div>
                </td>
                <td className="num">{formatDateTime(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && (
        <div className="empty" role="alert">
          <strong>{tab.label} could not be loaded</strong>
          <span>{error}</span>
          <button className="btn" onClick={() => void load()}>
            Retry
          </button>
        </div>
      )}
      {rows?.length === 0 && !error && (
        <div className="empty">
          <strong>Nothing here yet</strong>
          <span>{tab.empty}</span>
        </div>
      )}
    </section>
  );
}

export function SupportDesk() {
  return (
    <>
      <div className="page-head">
        <div style={{ display: 'grid', gap: 4 }}>
          <h1>Customer service desk</h1>
          <span className="muted small">Every call the voice agent takes, and the tickets, complaints and routed queries it raised.</span>
        </div>
        <Link to={Route.SUPPORT_NEW} className="btn primary">
          Start a call
        </Link>
      </div>
      <CallsPanel />
      <RecordsPanel />
    </>
  );
}
