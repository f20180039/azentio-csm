import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { CASE_STATUSES, CaseStatus, type CaseSummary, type RulePackInfo, type Stats } from '../api/types';
import { ScoreBar, StatusPill } from '../components/StatusPill';
import { Select } from '../components/Select';
import { useToast } from '../components/Toasts';
import { UploadDialog } from '../components/UploadDialog';
import { formatAge, formatInr, humanise } from '../format';
import { Route } from '../routes';

const REFRESH_MS = 3000;

function FilterIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
      <path d="M2 4h12M4.5 8h7M7 12h2" />
    </svg>
  );
}

export function Queue() {
  const [params, setParams] = useSearchParams();
  const status = (params.get('status') ?? '') as CaseStatus | '';
  const caseType = params.get('caseType') ?? '';
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [packs, setPacks] = useState<RulePackInfo[]>([]);
  const [uploading, setUploading] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();
  const errorShown = useRef(false);

  const load = useCallback(async () => {
    try {
      const [page, s] = await Promise.all([api.listCases({ status, caseType }), api.getStats().catch(() => null)]);
      setCases(page.items);
      setStats(s);
      errorShown.current = false;
    } catch (e) {
      if (!errorShown.current) toast.error(e);
      errorShown.current = true;
      setCases((c) => c ?? []);
    }
  }, [status, caseType, toast]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    api.listPacks().then(setPacks).catch(() => setPacks([]));
  }, []);

  const processing = cases?.some((c) => c.status === CaseStatus.PROCESSING || c.status === CaseStatus.RECEIVED) ?? false;
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [processing, load]);

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="sub">Highest risk and largest amount first. {processing && 'Refreshing while cases process.'}</p>
        </div>
        <div className="row">
          <div className="stats" aria-label="Pipeline stats">
            <div className="stat">
              <span className="label">Jobs pending</span>
              <span className="v">{stats?.jobsPending ?? '—'}</span>
            </div>
            <div className="stat">
              <span className="label">p95 processing</span>
              <span className="v">{stats?.p95Ms != null ? `${(stats.p95Ms / 1000).toFixed(1)}s` : '—'}</span>
            </div>
            <div className="stat">
              <span className="label">Cache hits</span>
              <span className="v">{stats?.cacheHits ?? '—'}</span>
            </div>
          </div>
          <button className="btn primary" onClick={() => setUploading(true)}>
            New case
          </button>
        </div>
      </div>

      <div className="filters">
        <label className="sr-only" htmlFor="filter-status">
          Status
        </label>
        <Select
          id="filter-status"
          value={status}
          onChange={(v) => setFilter('status', v)}
          icon={<FilterIcon />}
          options={[
            { value: '', label: 'All statuses' },
            ...CASE_STATUSES.map((s) => ({
              value: s,
              label: `${humanise(s)}${stats?.byStatus?.[s] != null ? ` (${stats.byStatus[s]})` : ''}`,
            })),
          ]}
        />
        <label className="sr-only" htmlFor="filter-type">
          Case type
        </label>
        <Select
          id="filter-type"
          value={caseType}
          onChange={(v) => setFilter('caseType', v)}
          options={[{ value: '', label: 'All case types' }, ...packs.map((p) => ({ value: p.caseType, label: p.label ?? humanise(p.caseType) }))]}
        />
        {(status || caseType) && (
          <button className="btn ghost sm" onClick={() => setParams({}, { replace: true })}>
            Clear filters
          </button>
        )}
      </div>

      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Case type</th>
              <th>Title</th>
              <th>Risk</th>
              <th className="r">₹ at risk</th>
              <th className="r">Findings</th>
              <th className="r">Age</th>
            </tr>
          </thead>
          <tbody>
            {cases === null && (
              <tr>
                <td colSpan={7} className="muted">
                  Loading cases…
                </td>
              </tr>
            )}
            {cases?.map((c) => (
              <tr
                key={c.id}
                className="clickable"
                tabIndex={0}
                onClick={() => navigate(Route.case(c.id))}
                onKeyDown={(e) => e.key === 'Enter' && navigate(Route.case(c.id))}
              >
                <td>
                  <StatusPill status={c.status} />
                </td>
                <td className="small">{packs.find((p) => p.caseType === c.caseType)?.label ?? humanise(c.caseType)}</td>
                <td className="title-cell">{c.title}</td>
                <td>
                  <ScoreBar score={c.riskScore} />
                </td>
                <td className="r num">{formatInr(c.amountAtRisk)}</td>
                <td className="r num">{c.findingsCount}</td>
                <td className="r num muted">{formatAge(c.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {cases?.length === 0 && (
          <div className="empty">
            <strong>No cases match</strong>
            <span>{status || caseType ? 'Clear the filters, or upload a document.' : 'Upload a document with New case to start.'}</span>
          </div>
        )}
      </div>

      {uploading && (
        <UploadDialog
          onClose={() => setUploading(false)}
          onUploaded={(r) => {
            setUploading(false);
            navigate(Route.case(r.case.id));
          }}
        />
      )}
    </>
  );
}
