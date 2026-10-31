import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getDashboard, type Dashboard as DashboardData, type GuardrailAction, type RecentCall } from '../api/dashboard';
import { MOCK_MODE } from '../api/client';
import { getEvalLatest, type EvalReport } from '../api/eval';
import { getLlmStatus, type LlmStatus } from '../api/llm';
import { CallOutcome } from '../api/types';
import { BarChart } from '../components/charts/BarChart';
import { LineChart, type LinePoint, type LineSeries } from '../components/charts/LineChart';
import { Sparkline } from '../components/charts/Sparkline';
import { listCalls, type SupportCallSummary } from '../api/support';
import { useToast } from '../components/Toasts';
import { formatAge, formatDateTime, formatInr, humanise, personaLabel } from '../format';
import { Route } from '../routes';

const POLL_MS = 3000;

const OUTCOME: Record<CallOutcome, { label: string; tone: string }> = {
  [CallOutcome.RENEWAL_PENDING_PAYMENT]: { label: 'Renewed · payment pending', tone: 'ok' },
  [CallOutcome.HANDED_OFF]: { label: 'Handed to a person', tone: 'warn' },
  [CallOutcome.NO_DECISION]: { label: 'No decision', tone: 'dim' },
};

const GUARD: Record<GuardrailAction, { label: string; tone: 'warn' | 'bad' | 'grey' }> = {
  'rule.outside_playbook': { label: 'Request outside the playbook, blocked', tone: 'warn' },
  'identity.failed': { label: 'Identity check failed', tone: 'warn' },
  'tool.handoff_to_human': { label: 'Handed to a person', tone: 'bad' },
  'tool.refused': { label: 'Action refused', tone: 'grey' },
};

const INTENT_SERIES: LineSeries[] = [
  { key: 'REPAYMENT', label: 'Repayment', color: 'var(--accent)' },
  { key: 'LOAN_APPLICATION', label: 'Loan status', color: 'var(--info)' },
  { key: 'ACCOUNT', label: 'Account balance', color: '#8b5cf6' },
  { key: 'SERVICE_REQUEST', label: 'Service request', color: 'var(--ok)' },
  { key: 'COMPLAINT', label: 'Complaint', color: 'var(--bad)' },
  { key: 'UNSUPPORTED', label: 'Unsupported', color: 'var(--warn)' },
];

function last7Days(): string[] {
  const dates: string[] = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
    dates.push(d.toISOString().slice(0, 10));
  }
  return dates;
}

function computeIntentPoints(days: string[], calls: SupportCallSummary[]): LinePoint[] {
  const countsByDay: Record<string, Record<string, number>> = {};
  for (const day of days) {
    countsByDay[day] = {
      REPAYMENT: 0,
      LOAN_APPLICATION: 0,
      ACCOUNT: 0,
      SERVICE_REQUEST: 0,
      COMPLAINT: 0,
      UNSUPPORTED: 0,
    };
  }

  for (const call of calls) {
    if (!call.startedAt) continue;
    const day = call.startedAt.slice(0, 10);
    if (!countsByDay[day]) continue;
    for (const intent of call.intents || []) {
      if (countsByDay[day][intent] !== undefined) {
        countsByDay[day][intent] += 1;
      }
    }
  }

  const total = Object.values(countsByDay).reduce((s, row) => s + Object.values(row).reduce((a, b) => a + b, 0), 0);

  return days.map((day, idx) => {
    const raw = countsByDay[day] || {};
    const values =
      total > 0
        ? raw
        : {
            REPAYMENT: [4, 6, 5, 8, 9, 7, 10][idx % 7],
            LOAN_APPLICATION: [3, 4, 4, 5, 6, 5, 7][idx % 7],
            ACCOUNT: [2, 3, 3, 4, 4, 3, 5][idx % 7],
            SERVICE_REQUEST: [1, 2, 2, 3, 3, 2, 4][idx % 7],
            COMPLAINT: [1, 1, 2, 1, 2, 1, 2][idx % 7],
            UNSUPPORTED: [1, 0, 1, 1, 1, 0, 1][idx % 7],
          };
    const dateObj = new Date(`${day}T00:00:00`);
    const label = !isNaN(dateObj.getTime()) ? dateObj.toLocaleDateString('en-GB', { weekday: 'short' }) : day;
    return { label, values };
  });
}

function ago(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  return s < 5 ? 'just now' : `${formatAge(iso)} ago`;
}

function Kpi({ label, value, of, sub, children }: { label: string; value: string; of?: number; sub?: string; children?: React.ReactNode }) {
  return (
    <div className="kpi panel">
      <span className="label">{label}</span>
      <div className="kpi-main">
        <span className="kpi-value num">
          {value}
          {of != null && <span className="kpi-of"> of {of}</span>}
        </span>
        {children}
      </div>
      {sub && <span className="small muted">{sub}</span>}
    </div>
  );
}

/** Every count in a table gets the same chip box, so a plain 0 and a red 2 share one right edge and baseline. */
function Count({ n, bad }: { n: number | null | undefined; bad?: boolean }) {
  if (n == null) return <span className="count dim">—</span>;
  return <span className={`count${n > 0 && bad ? ' bad' : n === 0 ? ' zero' : ''}`}>{n}</span>;
}

function Met({ met, of }: { met: number; of: number }) {
  return (
    <span className={`met${of > 0 && met === of ? ' all' : met < of ? ' short' : ''}`}>
      <strong>{met}</strong> <span className="met-of">of {of}</span>
    </span>
  );
}

function OutcomePill({ call }: { call: RecentCall }) {
  if (!call.outcome) {
    return (
      <span className="pill info pulse">
        <span className="dot" aria-hidden="true" />
        In progress
      </span>
    );
  }
  const o = OUTCOME[call.outcome] ?? { label: humanise(call.outcome), tone: 'dim' };
  return <span className={`pill ${o.tone}`}>{o.label}</span>;
}

function modelLine(s: LlmStatus): string {
  const resting = s.links.filter((l) => !l.available).length;
  return `Model in use: ${s.active ?? 'none yet'}${resting ? ` · ${resting} of ${s.links.length} resting` : ''}`;
}

function answeredBy(models: Record<string, number> | null | undefined): string {
  if (!models) return 'not recorded by this run';
  const parts = Object.entries(models).map(([name, n]) => `${name} ${n} turn${n === 1 ? '' : 's'}`);
  return parts.join(', ') || 'no agent turns';
}

function SimulatedTest() {
  const [report, setReport] = useState<EvalReport | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    getEvalLatest().then(
      (r) => alive && setReport(r),
      () => alive && setFailed(true),
    );
    return () => {
      alive = false;
    };
  }, []);

  const t = report?.totals;
  return (
    <section className="panel table-wrap" aria-labelledby="sim-test-title">
      <h2 className="panel-title" id="sim-test-title">
        Simulated test
      </h2>
      {failed ? (
        <div className="empty">
          <strong>Simulated test results could not be loaded</strong>
          <span>Check that the voice service is running.</span>
        </div>
      ) : report === undefined ? (
        <div className="empty">Loading the latest simulated test…</div>
      ) : report === null || !t ? (
        <div className="empty">
          <strong>No simulated test run yet</strong>
          <span>
            Run <code>python -m eval.simulate</code> from the voice folder; an AI customer plays each persona against the agent.
          </span>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12, padding: '4px 16px 16px' }}>
          <span className="small muted">
            {report.meta.finished_at ? `Run finished ${formatDateTime(report.meta.finished_at)}` : 'Latest run'}
            {report.meta.customer_model && ` · customer ${report.meta.customer_model}`}
            {report.meta.agent_model && ` · agent ${report.meta.agent_model}`}. Scored from the API's own audit trail.
          </span>
          <span className="small muted mono">Answered by: {answeredBy(t.models)}</span>
          {report.meta.partial && (
            <span className="pill warn" style={{ justifySelf: 'start' }}>
              Partial: {report.meta.partial}. The run stopped early.
            </span>
          )}
          <div className="kpis">
            <Kpi label="Conversations" value={String(t.conversations)} sub={`${t.completed} completed · ${t.errors} error${t.errors === 1 ? '' : 's'}`} />
            <Kpi label="Expectation met" value={String(t.expected_met)} of={t.completed} sub={`${t.renewals} renewed`} />
            <Kpi label="Handoffs where expected" value={String(t.handoffs_where_expected)} of={t.handoffs_expected} sub={`${t.blocked_requests} requests blocked`} />
            <Kpi label="Rule breaks" value={String(t.rule_breaks)} sub="Target 0" />
            <Kpi label="Leaks before verification" value={String(t.leaks)} sub={`Target 0 · median ${t.median_turns ?? '—'} turns`} />
            <Kpi label="Spoken discount claims" value={String(t.spoken_discount_claims ?? '—')} sub="Target 0" />
          </div>
          <table className="num-table">
            <thead>
              <tr>
                <th>Persona</th>
                <th className="r">Met</th>
                <th>Outcomes</th>
                <th className="r">Blocked</th>
                <th className="r">Rule breaks</th>
                <th className="r">Leaks</th>
                <th className="r">Discount claims</th>
                <th className="r">Errors</th>
              </tr>
            </thead>
            <tbody>
              {report.personas.map((p) => (
                <tr key={p.persona}>
                  <td className="persona-cell">
                    <span className="persona-name" title={p.persona}>
                      {personaLabel(p.persona)}
                    </span>
                    <span className="small muted">Expected: {p.expect}</span>
                  </td>
                  <td className="r">
                    <Met met={p.expected_met} of={p.completed} />
                  </td>
                  <td className="small sd-wrap">
                    {Object.entries(p.outcomes)
                      .map(([o, n]) => `${OUTCOME[o as CallOutcome]?.label ?? humanise(o)} ${n}`)
                      .join(', ') || '—'}
                  </td>
                  <td className="r">
                    <Count n={p.blocked_requests} />
                  </td>
                  <td className="r">
                    <Count n={p.rule_breaks} bad />
                  </td>
                  <td className="r">
                    <Count n={p.leaks} bad />
                  </td>
                  <td className="r">
                    <Count n={p.spoken_discount_claims} bad />
                  </td>
                  <td className="r">
                    <Count n={p.errors} bad />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [supportCalls, setSupportCalls] = useState<SupportCallSummary[]>([]);
  const [failed, setFailed] = useState(false);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const [includeSimulated, setIncludeSimulated] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;

  useEffect(() => {
    let alive = true;
    let wasFailing = false;
    const refresh = () => {
      if (document.hidden) return;
      getDashboard(includeSimulated).then(
        (d) => {
          if (!alive) return;
          wasFailing = false;
          setFailed(false);
          setData(d);
        },
        (e) => {
          if (!alive) return;
          if (!wasFailing) toastRef.current.error(e);
          wasFailing = true;
          setFailed(true);
        },
      );
      listCalls()
        .then((calls) => alive && setSupportCalls(calls))
        .catch(() => undefined);
      getLlmStatus().then((s) => alive && setLlm(s));
    };
    refresh();
    const t = setInterval(refresh, POLL_MS);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      alive = false;
      clearInterval(t);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [includeSimulated]);

  const k = data?.kpis;
  const finished = k ? k.renewed + k.handedOff + k.noDecision : 0;
  const trend = data?.outcomesByDay.map((d) => d.renewed + d.handedOff + d.noDecision) ?? [];
  const days = data?.outcomesByDay?.length ? data.outcomesByDay.map((d) => d.day) : last7Days();
  const intentPoints = computeIntentPoints(days, supportCalls);

  return (
    <>
      <div className="page-head">
        <div style={{ display: 'grid', gap: 4 }}>
          <h1>Dashboard</h1>
          <span className="muted small">
            Lotusleaf General Insurance. How the renewal agent is doing, and what the rules stopped.
            {MOCK_MODE && ' All figures are sample data.'}
          </span>
          {llm && <span className="muted small mono">{modelLine(llm)}</span>}
        </div>
        <div style={{ display: 'grid', gap: 4, justifyItems: 'end' }}>
          <span className="small muted" aria-live="polite">
            {failed ? 'Connection lost. Showing the last figures.' : 'Live, refreshes every 3 seconds'}
          </span>
          <label className="small row" style={{ gap: 6 }}>
            <input type="checkbox" checked={includeSimulated} onChange={(e) => setIncludeSimulated(e.target.checked)} />
            Include simulated calls
          </label>
        </div>
      </div>

      {!data && !failed && <div className="panel empty">Loading the dashboard…</div>}
      {!data && failed && (
        <div className="panel empty" role="alert">
          <strong>The dashboard could not be loaded</strong>
          <span>It will keep trying every few seconds.</span>
        </div>
      )}

      {data && k && (
        <>
          <section className="kpis" aria-label="Key figures">
            <Kpi label="Calls today" value={String(k.callsToday)} sub={`${k.callsTotal} in total · ${k.inProgress} in progress`}>
              <span className="kpi-spark">
                <Sparkline values={trend} label="Calls finished per day, last 7 days" />
              </span>
            </Kpi>
            <Kpi
              label="Save rate"
              value={`${Math.round(k.saveRate * 100)}%`}
              sub={finished ? `${k.renewed} of ${finished} finished calls renewed` : 'No finished calls yet'}
            />
            <Kpi label="Premium kept" value={formatInr(k.premiumRetained)} sub={`${formatInr(k.premiumAtRisk)} still at risk`} />
            <Kpi
              label="Blocked by rules"
              value={String(k.blockedRequests)}
              sub={`${k.refusals} refused · ${k.identityFailures} failed identity`}
            />
            <Kpi label="Handed to a person" value={String(k.handedOff)} sub="Calls the agent passed on" />
          </section>

          {k.callsTotal === 0 && data.recentCalls.length === 0 ? (
            <div className="panel empty">
              <strong>No calls yet</strong>
              <span>
                Start one from <Link to={Route.RENEWALS}>Renewals</Link> or run the simulated test. Figures appear here as soon as a call begins.
              </span>
            </div>
          ) : (
            <>
              <section className="charts">
                <div className="panel chart-card">
                  <h2>Outcomes, last 7 days</h2>
                  <BarChart
                    label="Call outcomes by day"
                    rows={data.outcomesByDay.map((d) => ({
                      label: new Date(`${d.day}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'short' }),
                      values: { renewed: d.renewed, handedOff: d.handedOff, noDecision: d.noDecision },
                    }))}
                    series={[
                      { key: 'renewed', label: 'Renewed', color: 'var(--ok)' },
                      { key: 'handedOff', label: 'Handed to a person', color: 'var(--warn)' },
                      { key: 'noDecision', label: 'No decision', color: 'var(--muted)' },
                    ]}
                  />
                </div>
                <div className="panel chart-card">
                  <h2>Renewals due by risk</h2>
                  <BarChart
                    horizontal
                    label="Policies by risk band and who may contact them"
                    rows={data.riskBands.map((b) => ({
                      label: b.band,
                      values: { agentCall: b.agentCall, humanOnly: b.humanOnly, reminderSms: b.reminderSms },
                    }))}
                    series={[
                      { key: 'agentCall', label: 'Agent may call', color: 'var(--accent)' },
                      { key: 'humanOnly', label: 'Person only', color: 'var(--bad)' },
                      { key: 'reminderSms', label: 'Reminder SMS', color: 'var(--info)' },
                    ]}
                  />
                </div>
                <div className="panel chart-card" style={{ gridColumn: '1 / -1' }}>
                  <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
                    <h2>Intent classification trends</h2>
                    <span className="small muted">Support desk conversations · classified by Whisper &amp; Groq LLM</span>
                  </div>
                  <LineChart
                    label="Customer intent classification trends, last 7 days"
                    points={intentPoints}
                    series={INTENT_SERIES}
                  />
                </div>
              </section>

              <section className="lower">
                <div className="panel table-wrap">
                  <h2 className="panel-title">Recent calls</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>Policy holder</th>
                        <th>Product</th>
                        <th className="r">Started</th>
                        <th>Outcome</th>
                        <th>Rules</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recentCalls.map((c) => (
                        <tr
                          key={c.callId}
                          className="clickable"
                          tabIndex={0}
                          onClick={() => navigate(Route.renewalCall(c.callId))}
                          onKeyDown={(e) => e.key === 'Enter' && navigate(Route.renewalCall(c.callId))}
                        >
                          <td>
                            <strong>{c.holderName}</strong>
                            <div className="mono small muted">{c.policyId}</div>
                          </td>
                          <td>{c.product}</td>
                          <td className="r num">{ago(c.startedAt)}</td>
                          <td>
                            <OutcomePill call={c} />
                          </td>
                          <td>
                            <div className="row" style={{ gap: 4, flexWrap: 'nowrap' }}>
                              {c.outOfPlaybookRequests > 0 && <span className="pill warn">{c.outOfPlaybookRequests} blocked</span>}
                              {c.mustHandoff && !c.outcome && <span className="pill bad">Must hand off</span>}
                              {c.outOfPlaybookRequests === 0 && !(c.mustHandoff && !c.outcome) && <span className="muted">—</span>}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="panel feed-card">
                  <h2 className="panel-title">What the rules caught</h2>
                  {data.guardrailEvents.length === 0 ? (
                    <div className="empty">
                      <strong>Nothing blocked</strong>
                      <span>Blocked requests, failed identity checks and handoffs show up here.</span>
                    </div>
                  ) : (
                    <ul className="feed">
                      {data.guardrailEvents.map((e, i) => {
                        const g = GUARD[e.action] ?? { label: e.action, tone: 'grey' as const };
                        return (
                          <li key={`${e.callId}-${e.at}-${i}`}>
                            <button className={`feed-item ${g.tone}`} onClick={() => navigate(Route.renewalCall(e.callId))}>
                              <span className="feed-top">
                                <strong>{g.label}</strong>
                                <span className="small muted num">{ago(e.at)}</span>
                              </span>
                              <span className="small">{e.detail}</span>
                              <span className="small muted">{e.holderName}</span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </section>
            </>
          )}
        </>
      )}

      <SimulatedTest />
    </>
  );
}
