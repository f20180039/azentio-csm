import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../api/errors';
import { getQueue, startCall } from '../api/renewals';
import { RenewalRoute, type QueueItem, type Severity } from '../api/types';
import { ScoreBar } from '../components/StatusPill';
import { useToast } from '../components/Toasts';
import { humanise } from '../format';
import { Route } from '../routes';

const SEV_TONE: Record<Severity, string> = { HIGH: 'bad', MEDIUM: 'warn', LOW: 'info' };

const REFUSALS: Record<string, string> = {
  HUMAN_ONLY: 'This policy is for a person to call: the agent may not.',
  DO_NOT_CALL: 'This customer is on the do-not-call list.',
  OUTSIDE_CALLING_HOURS: 'Outside permitted calling hours. Try again in the calling window.',
};

function RouteCell({ item, busy, onStart }: { item: QueueItem; busy: boolean; onStart: () => void }) {
  const route: RenewalRoute = item.route;
  if (route === RenewalRoute.AGENT_CALL) {
    return (
      <button className="btn primary sm" onClick={onStart} disabled={busy}>
        {busy ? 'Starting…' : 'Start agent call'}
      </button>
    );
  }
  return <span className="muted small">{route === RenewalRoute.HUMAN_ONLY ? 'Agent may not call' : 'Reminder SMS'}</span>;
}

export function Renewals() {
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const navigate = useNavigate();
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;

  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoadError(null);
    setItems(null);
    getQueue()
      .then(setItems)
      .catch((e) => {
        toastRef.current.error(e);
        setLoadError(e instanceof Error ? e.message : 'The renewals queue could not be loaded.');
        setItems([]);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function start(policyId: string) {
    setStarting(policyId);
    try {
      const c = await startCall(policyId);
      navigate(Route.renewalCall(c.callId));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail) {
        toast.push('Call not started', REFUSALS[e.detail] ?? e.detail, 'warn');
      } else {
        toast.error(e);
      }
    } finally {
      setStarting(null);
    }
  }

  return (
    <>
      <div className="page-head">
        <div style={{ display: 'grid', gap: 4 }}>
          <h1>Renewals due</h1>
          <span className="muted small">Lotusleaf General Insurance. Ranked by renewal risk; the route decides who may call.</span>
        </div>
      </div>
      <div className="panel table-wrap">
        <table>
          <thead>
            <tr>
              <th>Policy holder</th>
              <th>Product</th>
              <th>Expires</th>
              <th>Risk</th>
              <th>Signals</th>
              <th>Route</th>
            </tr>
          </thead>
          <tbody>
            {items === null && (
              <tr>
                <td colSpan={6} className="muted">
                  Loading renewals…
                </td>
              </tr>
            )}
            {items?.map((q) => (
              <tr key={q.policyId}>
                <td className="title-cell">
                  <strong>{q.holderName}</strong>
                  <div className="mono small muted">{q.policyId}</div>
                </td>
                <td>{q.product}</td>
                <td className="num">
                  {q.expiresOn}
                  <div className="small muted">{q.daysToExpiry} days</div>
                </td>
                <td>
                  <ScoreBar score={q.score} />
                </td>
                <td>
                  <div className="row" style={{ gap: 4 }}>
                    {q.signals.map((s) => (
                      <span key={s.code} className={`pill ${SEV_TONE[s.severity]}`} title={`${humanise(s.severity)} · weight ${s.weight}`}>
                        {s.label}
                      </span>
                    ))}
                  </div>
                </td>
                <td>
                  <RouteCell item={q} busy={starting === q.policyId} onStart={() => start(q.policyId)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loadError && (
          <div className="empty" role="alert">
            <strong>The renewals queue could not be loaded</strong>
            <span>{loadError}</span>
            <button className="btn" onClick={load}>
              Retry
            </button>
          </div>
        )}
        {items?.length === 0 && !loadError && (
          <div className="empty">
            <strong>No renewals due</strong>
            <span>Policies expiring soon appear here once the API has scored them.</span>
          </div>
        )}
      </div>
    </>
  );
}
