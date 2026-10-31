import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  CHANNEL_LABEL,
  intentLabel,
  intentTone,
  listCalls,
  listRecords,
  OUTCOME_LABEL,
  OUTCOME_TONE,
  RECORD_STATUS_TONE,
  SUPPORT_OUTCOMES,
  TICKET_STATUSES,
  RecordKind,
  TicketStatus,
  updateTicket,
  type OpsRecord,
  type SupportCallSummary,
  type SupportOutcome,
} from '../api/support';
import { CUSTOMER_ID_LABEL } from '../components/CustomerCard';
import { NoResults, SearchBox, useUrlQuery } from '../components/SearchBox';
import { Select, type SelectOption } from '../components/Select';
import { Stars } from '../components/Stars';
import { formatDateTime, humanise } from '../format';
import { Route } from '../routes';
import { Highlight, matches, SearchParam } from '../search';

const REFRESH_MS = 5000;

const RECORD_TABS: { kind: RecordKind; label: string; empty: string }[] = [
  { kind: RecordKind.TICKET, label: 'Tickets', empty: 'No service requests yet.' },
  { kind: RecordKind.COMPLAINT, label: 'Complaints', empty: 'No complaints registered yet.' },
  { kind: RecordKind.ROUTED, label: 'Routed queries', empty: 'No unsupported questions routed yet.' },
  { kind: RecordKind.ESCALATION, label: 'Escalations', empty: 'No calls escalated yet.' },
];

const ALL_RECORD_KINDS = RECORD_TABS.map((t) => t.kind);

const TICKET_STATUS_OPTIONS: SelectOption[] = TICKET_STATUSES.map((s) => ({ value: s, label: humanise(s) }));

const failedOpsText = (n: number | undefined) => (n ? `${n} failed` : null);

function callMatches(q: string, c: SupportCallSummary): boolean {
  return matches(
    q,
    c.id,
    c.intents,
    c.intents.map(intentLabel),
    c.outcome,
    c.outcome ? OUTCOME_LABEL[c.outcome] : c.endedAt ? 'Ended' : 'Live',
    c.channel,
    CHANNEL_LABEL[c.channel],
    c.verified ? 'Verified' : 'Not verified',
    failedOpsText(c.failedOps),
  );
}

function recordMatches(q: string, r: OpsRecord): boolean {
  return matches(
    q,
    r.ref,
    r.category,
    r.category && humanise(r.category),
    r.status,
    r.status && humanise(r.status),
    r.summary,
    r.customer_ref,
    r.customer_name,
    r.call_id,
    r.department,
    r.progress,
    r.original_statement,
    r.related_ref,
    r.related_refs ?? [],
  );
}

function isTicketStatus(s: string | null): s is TicketStatus {
  return (TICKET_STATUSES as string[]).includes(s ?? '');
}

/**
 * Moves a service request to a new status, with the note the caller then hears about its progress.
 * The status and note are staged and sent only on Save (or Enter in the note), so a stray keypress on the
 * status button never moves a ticket on its own.
 */
function TicketControls({ r, onUpdated }: { r: OpsRecord; onUpdated: (updated: OpsRecord) => void }) {
  const [staged, setStaged] = useState<TicketStatus | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = isTicketStatus(r.status) ? r.status : TicketStatus.OPEN;
  const status = staged ?? current;
  const changed = staged !== null || note.trim() !== '';

  async function save() {
    if (!changed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await updateTicket(r.ref, status, note.trim() || null);
      onUpdated(updated);
      setStaged(null);
      setNote('');
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sd-ticket-controls" aria-busy={busy}>
      <Select
        aria-label={`Status of ${r.ref}`}
        value={status}
        options={TICKET_STATUS_OPTIONS}
        onChange={(v) => setStaged(v === current ? null : (v as TicketStatus))}
        disabled={busy}
      />
      <input
        type="text"
        aria-label={`Progress note for ${r.ref}`}
        placeholder="Progress note the caller will hear"
        value={note}
        readOnly={busy}
        onChange={(e) => setNote(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            void save();
          }
        }}
      />
      <button type="button" className="btn" aria-label={`Save ${r.ref}`} disabled={!changed || busy} onClick={() => void save()}>
        {busy ? 'Saving…' : 'Save'}
      </button>
      {error && (
        <span className="small bad-text" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

function RefPills({ refs, query }: { refs: string[]; query: string }) {
  return (
    <>
      {refs.map((ref) => (
        <span key={ref} className="ref-pill">
          <Highlight text={ref} query={query} />
        </span>
      ))}
    </>
  );
}

/** People see names, not ids: the customer's name leads; the CUST- id follows small and muted for staff cross-referencing.
 * Falls back to the id alone when a record carries no name; nothing at all when it has no customer. */
function CustomerLabel({ r, query }: { r: OpsRecord; query: string }) {
  if (!r.customer_ref) return null;
  if (!r.customer_name) {
    return (
      <span className="mono muted" title={CUSTOMER_ID_LABEL}>
        <Highlight text={r.customer_ref} query={query} />
      </span>
    );
  }
  return (
    <span className="sd-customer">
      <Highlight text={r.customer_name} query={query} />
      <span className="mono muted sd-customer-id" title={CUSTOMER_ID_LABEL}>
        <Highlight text={r.customer_ref} query={query} />
      </span>
    </span>
  );
}

/** What a record adds beneath its summary: where a ticket stands, a complaint in the caller's words, what an escalation concerns. */
function RecordDetail({ r, query }: { r: OpsRecord; query: string }) {
  return (
    <>
      {r.progress && (
        <div className="small">
          <Highlight text={r.progress} query={query} />
        </div>
      )}
      {r.original_statement && (
        <div className="small sd-quote">
          <Highlight text={`“${r.original_statement}”`} query={query} />
        </div>
      )}
      {(r.related_ref || !!r.related_refs?.length) && (
        <div className="row small muted" style={{ gap: 4 }}>
          About <RefPills refs={r.related_ref ? [r.related_ref] : r.related_refs ?? []} query={query} />
        </div>
      )}
    </>
  );
}

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function CallStatusPill({ c, query = '' }: { c: Pick<SupportCallSummary, 'endedAt' | 'outcome'>; query?: string }) {
  if (!c.endedAt) {
    return (
      <span className="pill info pulse">
        <span className="dot" aria-hidden="true" />
        <Highlight text="Live" query={query} />
      </span>
    );
  }
  const o = c.outcome;
  return (
    <span className={`pill ${o ? OUTCOME_TONE[o] : 'dim'}`}>
      <span className="dot" aria-hidden="true" />
      <Highlight text={o ? OUTCOME_LABEL[o] : 'Ended'} query={query} />
    </span>
  );
}

function CallsPanel() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<SupportOutcome | ''>('');
  const [calls, setCalls] = useState<SupportCallSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useUrlQuery(SearchParam.QUERY);
  const shown = useMemo(() => calls?.filter((c) => callMatches(query, c)) ?? null, [calls, query]);
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
      <div className="search-bar">
        <SearchBox
          value={query}
          onChange={setQuery}
          label="Search calls"
          placeholder="Search calls by intent, outcome, channel or id"
          shown={shown?.length}
          total={calls?.length}
        />
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
              <th>Rating</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {calls === null && (
              <tr>
                <td colSpan={7} className="muted">
                  Loading calls…
                </td>
              </tr>
            )}
            {shown?.map((c) => (
              <tr key={c.id} className="clickable" tabIndex={0} onClick={() => open(c.id)} onKeyDown={(e) => onRowKey(e, c.id)} aria-label={`Open call started ${formatDateTime(c.startedAt)}`}>
                <td className="num">{formatDateTime(c.startedAt)}</td>
                <td>
                  <Highlight text={CHANNEL_LABEL[c.channel] ?? humanise(c.channel)} query={query} />
                </td>
                <td>
                  <span className={`pill ${c.verified ? 'ok' : 'dim'}`}>
                    <Highlight text={c.verified ? 'Verified' : 'Not verified'} query={query} />
                  </span>
                </td>
                <td className="sd-wrap">
                  <div className="row" style={{ gap: 4 }}>
                    {c.intents.length === 0 && <span className="muted small">—</span>}
                    {c.intents.map((i) => (
                      <span key={i} className={`pill ${intentTone(i)}`} title={i}>
                        <Highlight text={intentLabel(i)} query={query} />
                      </span>
                    ))}
                  </div>
                </td>
                <td className="num r">{c.turnCount}</td>
                <td>{c.rating ? <Stars score={c.rating.score} /> : <span className="muted small">—</span>}</td>
                <td>
                  <div className="row" style={{ gap: 4 }}>
                    <CallStatusPill c={c} query={query} />
                    {failedOpsText(c.failedOps) && (
                      <span className="pill bad" title="Tool calls that failed on this call">
                        <Highlight text={failedOpsText(c.failedOps)!} query={query} />
                      </span>
                    )}
                  </div>
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
      {!!calls?.length && shown?.length === 0 && <NoResults query={query} onClear={() => setQuery('')} />}
    </section>
  );
}

function RecordsPanel() {
  const [kind, setKind] = useState<RecordKind>(RecordKind.TICKET);
  const [byKind, setByKind] = useState<Partial<Record<RecordKind, OpsRecord[]>>>({});
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useUrlQuery(SearchParam.RECORDS_QUERY);
  const searching = query.trim() !== '';
  const kindRef = useRef(kind);
  kindRef.current = kind;
  const searchingRef = useRef(searching);
  searchingRef.current = searching;
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const loadKind = useCallback(async (wanted: RecordKind) => {
    try {
      const items = await listRecords(wanted);
      setByKind((m) => ({ ...m, [wanted]: items }));
      if (kindRef.current === wanted) setError(null);
    } catch (e) {
      if (kindRef.current !== wanted) return;
      setError(errorText(e));
      setByKind((m) => (m[wanted] ? m : { ...m, [wanted]: [] }));
    }
  }, []);

  /** The active tab always; every tab while searching, so the tab labels can show their match counts. */
  const load = useCallback(async () => {
    const active = kindRef.current;
    const others = searchingRef.current ? ALL_RECORD_KINDS.filter((k) => k !== active) : [];
    await Promise.all([active, ...others].map(loadKind));
  }, [loadKind]);

  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(t);
  }, [load, kind, searching]);

  const rows = byKind[kind] ?? null;
  const shown = useMemo(() => rows?.filter((r) => recordMatches(query, r)) ?? null, [rows, query]);
  const countFor = (k: RecordKind) => byKind[k]?.filter((r) => recordMatches(query, r)).length;

  /**
   * The simulator answers with the ticket's own fields: the row shows them at once, keeping what the list knew
   * (call, customer, time), then the kind reloads so a poll that started before the change cannot put stale data back.
   */
  const replaceRecord = useCallback(
    (updated: OpsRecord) => {
      setByKind((m) => ({
        ...m,
        [updated.kind]: (m[updated.kind] ?? []).map((r) =>
          r.ref === updated.ref ? { ...r, status: updated.status, progress: updated.progress ?? r.progress, department: updated.department ?? r.department } : r,
        ),
      }));
      void loadKind(updated.kind);
    },
    [loadKind],
  );

  const tab = RECORD_TABS.find((t) => t.kind === kind)!;
  const editable = kind === RecordKind.TICKET;
  const columns = editable ? 6 : 5;
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
      <div className="search-bar">
        <SearchBox
          value={query}
          onChange={setQuery}
          label="Search bank records"
          placeholder="Search records by reference, category, status or summary"
          shown={shown?.length}
          total={rows?.length}
          shortcut={false}
        />
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
            {searching && countFor(t.kind) != null && <span className="tab-count">{countFor(t.kind)}</span>}
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
              {editable && <th>Update</th>}
            </tr>
          </thead>
          <tbody>
            {rows === null && (
              <tr>
                <td colSpan={columns} className="muted">
                  Loading {tab.label.toLowerCase()}…
                </td>
              </tr>
            )}
            {shown?.map((r) => (
              <tr key={r.ref}>
                <td>
                  <span className="ref-pill">
                    <Highlight text={r.ref} query={query} />
                  </span>
                  {r.escalated && (
                    <span className="pill bad" style={{ marginLeft: 6 }}>
                      Escalated
                    </span>
                  )}
                </td>
                <td>
                  {r.category ? (
                    <span title={r.category}>
                      <Highlight text={humanise(r.category)} query={query} />
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                  {r.department && (
                    <div className="small muted">
                      <Highlight text={r.department} query={query} />
                    </div>
                  )}
                </td>
                <td>
                  {r.status ? (
                    <span className={`pill ${RECORD_STATUS_TONE[r.status] ?? 'dim'}`}>
                      <Highlight text={humanise(r.status)} query={query} />
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="sd-wrap sd-summary">
                  <Highlight text={r.summary} query={query} />
                  <RecordDetail r={r} query={query} />
                  <div className="small">
                    <CustomerLabel r={r} query={query} />
                    {r.call_id && (
                      <>
                        {r.customer_ref && <span className="muted"> · </span>}
                        <Link to={Route.supportCall(r.call_id)}>Open call</Link>
                      </>
                    )}
                  </div>
                </td>
                <td className="num">{formatDateTime(r.created_at)}</td>
                {editable && (
                  <td>
                    <TicketControls r={r} onUpdated={replaceRecord} />
                  </td>
                )}
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
      {!!rows?.length && shown?.length === 0 && <NoResults query={query} onClear={() => setQuery('')} />}
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
