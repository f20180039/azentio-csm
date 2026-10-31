import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  getCall,
  getInsights,
  LESSON_STATUS_LABEL,
  LESSON_STATUS_TONE,
  LessonStatus,
  listLessons,
  listRecords,
  listReview,
  OUTCOME_LABEL,
  OUTCOME_TONE,
  RecordKind,
  resolveReview,
  REVIEW_REASON_LABEL,
  ReviewReason,
  setLessonStatus,
  type Insights,
  type Lesson,
  type OpsRecord,
  type ReviewItem,
} from '../api/support';
import { BarChart } from '../components/charts/BarChart';
import { copyText, CopyDialog } from '../components/CopyDialog';
import { Stars } from '../components/Stars';
import { useToast } from '../components/Toasts';
import { displayName } from '../demoUsers';
import { faqDraft, groupFaqGaps, type FaqGap } from '../faqGaps';
import { formatDateTime } from '../format';
import { Route } from '../routes';
import { scenarioYaml } from '../scenarioExport';
import { useCanReview, useIsAdmin } from '../session';
import { LessonForm } from './CallFeedback';

const SCORES = ['5', '4', '3', '2', '1'] as const;

const REASON_TONE: Record<ReviewReason, string> = {
  [ReviewReason.LOW_RATING]: 'warn',
  [ReviewReason.DISSATISFIED]: 'bad',
  [ReviewReason.BAD_FEEDBACK]: 'bad',
};

type Loaded<T> = { data: T | null; error: string | null };
const empty = <T,>(): Loaded<T> => ({ data: null, error: null });
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

function useLoad<T>(fetcher: () => Promise<T>): [Loaded<T>, () => Promise<void>] {
  const [state, setState] = useState<Loaded<T>>(empty);
  const load = useCallback(async () => {
    try {
      setState({ data: await fetcher(), error: null });
    } catch (e) {
      setState((s) => ({ data: s.data, error: errorText(e) }));
    }
  }, [fetcher]);
  useEffect(() => void load(), [load]);
  return [state, load];
}

function LoadError({ what, error, retry }: { what: string; error: string; retry: () => void }) {
  return (
    <div className="empty" role="alert">
      <strong>{what} could not be loaded</strong>
      <span>{error}</span>
      <button className="btn" onClick={retry}>
        Retry
      </button>
    </div>
  );
}

/* ---------- summary ---------- */

function Summary({ insights }: { insights: Loaded<Insights> }) {
  const d = insights.data;
  const avg = d?.ratings.average;
  return (
    <div className="ins-summary">
      <section className="panel kpi ins-rating" aria-label="Customer ratings">
        <span className="label">Average rating</span>
        <div className="row" style={{ alignItems: 'baseline' }}>
          <span className="kpi-value" data-testid="avg-rating">
            {avg == null ? '—' : avg.toFixed(1)}
          </span>
          {avg != null && <Stars score={Math.round(avg)} size={16} />}
          <span className="small muted">{d ? `${d.ratings.count} rated call${d.ratings.count === 1 ? '' : 's'}` : 'Loading…'}</span>
        </div>
        {d && (
          <BarChart
            horizontal
            label="Ratings by score"
            rows={SCORES.map((s) => ({ label: `${s} ★`, values: { n: d.ratings.distribution[s] ?? 0 } }))}
            series={[{ key: 'n', label: 'Calls', color: 'var(--accent)' }]}
          />
        )}
      </section>
      <div className="ins-counts">
        {(
          [
            ['Low-rated calls', d?.lowRated, 'Rated 1 or 2'],
            ['Open reviews', d?.openReviews, 'Waiting for a reviewer'],
            ['Bad feedback', d?.badFeedback, 'Agent answers marked 👎'],
            ['Active lessons', d?.activeLessons, 'In the agent’s prompt'],
          ] as const
        ).map(([label, value, note]) => (
          <section key={label} className="panel kpi" aria-label={label}>
            <span className="label">{label}</span>
            <span className="kpi-value">{value ?? '—'}</span>
            <span className="small muted">{note}</span>
          </section>
        ))}
      </div>
    </div>
  );
}

/* ---------- review queue ---------- */

function ResolveForm({ id, onDone, onCancel }: { id: string; onDone: () => void; onCancel: () => void }) {
  const toast = useToast();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="ins-resolve"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await resolveReview(id, note.trim());
          toast.push('Marked reviewed');
          onDone();
        } catch (err) {
          toast.error(err);
          setBusy(false);
        }
      }}
    >
      <textarea aria-label="Review note" placeholder="What did you find? (kept in the audit trail)" rows={2} value={note} onChange={(e) => setNote(e.target.value)} disabled={busy} />
      <div className="row">
        <button type="button" className="btn ghost sm" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn primary sm" disabled={busy || !note.trim()}>
          {busy ? 'Saving…' : 'Mark reviewed'}
        </button>
      </div>
    </form>
  );
}

function ReviewQueue({ review, reload, onExport }: { review: Loaded<ReviewItem[]>; reload: () => void; onExport: (id: string) => void }) {
  const canReview = useCanReview();
  const [resolving, setResolving] = useState<string | null>(null);
  const items = review.data;
  const open = items?.filter((i) => !i.resolved).length ?? 0;
  return (
    <section className="panel" aria-labelledby="review-title">
      <div className="sd-panel-head">
        <h2 id="review-title">Review queue</h2>
        <span className="small muted">{items ? `${open} open · newest first` : 'Loading…'}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Call</th>
              <th>Outcome</th>
              <th>Rating</th>
              <th>Why</th>
              <th>State</th>
              <th className="r">Action</th>
            </tr>
          </thead>
          <tbody>
            {items?.map((r) => (
              <tr key={r.id} className={r.resolved ? 'is-done' : undefined}>
                <td>
                  <Link to={Route.supportCall(r.id)}>{formatDateTime(r.startedAt)}</Link>
                  <div className="mono small muted">{r.id}</div>
                </td>
                <td>{r.outcome ? <span className={`pill ${OUTCOME_TONE[r.outcome]}`}>{OUTCOME_LABEL[r.outcome]}</span> : <span className="muted">—</span>}</td>
                <td>{r.rating != null ? <Stars score={r.rating} /> : <span className="muted small">Not rated</span>}</td>
                <td className="sd-wrap">
                  <div className="row" style={{ gap: 4 }}>
                    {r.reasons.map((x) => (
                      <span key={x} className={`pill ${REASON_TONE[x] ?? 'dim'}`} title={x}>
                        {REVIEW_REASON_LABEL[x] ?? x}
                      </span>
                    ))}
                  </div>
                </td>
                <td>{r.resolved ? <span className="pill ok">Reviewed</span> : <span className="pill warn">Open</span>}</td>
                <td className="r sd-wrap">
                  {r.resolved ? (
                    <button type="button" className="btn sm" onClick={() => onExport(r.id)}>
                      Export as test scenario
                    </button>
                  ) : canReview && resolving !== r.id ? (
                    <button type="button" className="btn sm" onClick={() => setResolving(r.id)}>
                      Mark reviewed
                    </button>
                  ) : null}
                  {resolving === r.id && (
                    <ResolveForm
                      id={r.id}
                      onCancel={() => setResolving(null)}
                      onDone={() => {
                        setResolving(null);
                        reload();
                      }}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {review.error && <LoadError what="The review queue" error={review.error} retry={reload} />}
      {items?.length === 0 && !review.error && (
        <div className="empty">
          <strong>Nothing to review</strong>
          <span>Low ratings, unhappy endings and 👎 answers land here.</span>
        </div>
      )}
    </section>
  );
}

/* ---------- lessons ---------- */

function LessonsPanel({ lessons, reload }: { lessons: Loaded<Lesson[]>; reload: () => void }) {
  const toast = useToast();
  const isAdmin = useIsAdmin();
  const canReview = useCanReview();
  const [busy, setBusy] = useState<string | null>(null);
  const [proposing, setProposing] = useState(false);

  async function change(l: Lesson, status: typeof LessonStatus.ACTIVE | typeof LessonStatus.RETIRED) {
    setBusy(l.id);
    try {
      await setLessonStatus(l.id, status);
      toast.push(status === LessonStatus.ACTIVE ? 'Lesson activated' : 'Lesson retired', status === LessonStatus.ACTIVE ? 'The agent reads it on its next call.' : undefined);
      reload();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  }

  const order = [LessonStatus.PROPOSED, LessonStatus.ACTIVE, LessonStatus.RETIRED];
  const rows = [...(lessons.data ?? [])].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status) || b.createdAt.localeCompare(a.createdAt));

  return (
    <section className="panel" aria-labelledby="lessons-title">
      <div className="sd-panel-head">
        <div style={{ display: 'grid', gap: 2 }}>
          <h2 id="lessons-title">Lessons</h2>
          <span className="small muted">Active lessons are added to the agent’s instructions (at most 10).</span>
        </div>
        {canReview && !proposing && (
          <button type="button" className="btn sm" onClick={() => setProposing(true)}>
            Propose a lesson
          </button>
        )}
      </div>
      {canReview && proposing && (
        <div className="ins-propose">
          <LessonForm
            onCancel={() => setProposing(false)}
            onDone={() => {
              setProposing(false);
              reload();
            }}
          />
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Lesson</th>
              <th>Status</th>
              <th>Source</th>
              <th>Proposed by</th>
              <th className="r">{isAdmin ? 'Action' : ''}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((l) => (
              <tr key={l.id}>
                <td className="sd-wrap ins-lesson-text">{l.text}</td>
                <td>
                  <span className={`pill ${LESSON_STATUS_TONE[l.status] ?? 'dim'}`}>{LESSON_STATUS_LABEL[l.status] ?? l.status}</span>
                  {l.approvedBy && l.status === LessonStatus.ACTIVE && <div className="small muted">by {displayName(l.approvedBy)}</div>}
                </td>
                <td>
                  {l.sourceCallId ? (
                    <Link to={Route.supportCall(l.sourceCallId)}>
                      Call{l.sourceSeq != null ? `, turn ${l.sourceSeq}` : ''}
                    </Link>
                  ) : (
                    <span className="muted small">Written by hand</span>
                  )}
                </td>
                <td>
                  {displayName(l.author)}
                  <div className="small muted num">{formatDateTime(l.createdAt)}</div>
                </td>
                <td className="r">
                  {isAdmin && (
                    <span className="row" style={{ justifyContent: 'flex-end', gap: 4 }}>
                      {l.status !== LessonStatus.ACTIVE && (
                        <button type="button" className="btn primary sm" disabled={busy === l.id} onClick={() => void change(l, LessonStatus.ACTIVE)}>
                          Activate
                        </button>
                      )}
                      {l.status !== LessonStatus.RETIRED && (
                        <button type="button" className="btn sm" disabled={busy === l.id} onClick={() => void change(l, LessonStatus.RETIRED)}>
                          Retire
                        </button>
                      )}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {lessons.error && <LoadError what="Lessons" error={lessons.error} retry={reload} />}
      {lessons.data?.length === 0 && !lessons.error && (
        <div className="empty">
          <strong>No lessons yet</strong>
          <span>Propose one from a reviewer’s correction on a call, or write one here.</span>
        </div>
      )}
    </section>
  );
}

/* ---------- FAQ gaps ---------- */

function FaqGaps({ routed, reload, onShow }: { routed: Loaded<OpsRecord[]>; reload: () => void; onShow: (gap: FaqGap) => void }) {
  const toast = useToast();
  const gaps = useMemo(() => (routed.data ? groupFaqGaps(routed.data) : null), [routed.data]);
  async function copy(g: FaqGap) {
    if (await copyText(faqDraft(g))) toast.push('FAQ draft copied', g.examples[0]);
    else onShow(g);
  }
  return (
    <section className="panel" aria-labelledby="faq-title">
      <div className="sd-panel-head">
        <div style={{ display: 'grid', gap: 2 }}>
          <h2 id="faq-title">FAQ gaps</h2>
          <span className="small muted">Questions the agent routed because it had no approved answer, grouped by similar wording.</span>
        </div>
      </div>
      {gaps && gaps.length > 0 && (
        <ul className="ins-gaps">
          {gaps.map((g) => (
            <li key={g.refs.join()} className="ins-gap">
              <div className="ins-gap-count num" aria-label={`Asked ${g.count} times`}>
                {g.count}×
              </div>
              <div className="ins-gap-body">
                <strong>{g.examples[0]}</strong>
                {g.examples.length > 1 && <span className="small muted">Also: {g.examples.slice(1).map((e) => `“${e}”`).join(' · ')}</span>}
                <div className="row" style={{ gap: 4 }}>
                  {g.keywords.map((k) => (
                    <span key={k} className="pill dim">
                      {k}
                    </span>
                  ))}
                  {g.callIds.map((id) => (
                    <Link key={id} to={Route.supportCall(id)} className="small">
                      Open call
                    </Link>
                  ))}
                </div>
              </div>
              <button type="button" className="btn sm" onClick={() => void copy(g)}>
                Copy as FAQ draft
              </button>
            </li>
          ))}
        </ul>
      )}
      {routed.error && <LoadError what="Routed queries" error={routed.error} retry={reload} />}
      {gaps?.length === 0 && !routed.error && (
        <div className="empty">
          <strong>No routed questions</strong>
          <span>Every question so far had an approved answer.</span>
        </div>
      )}
    </section>
  );
}

/* ---------- the page ---------- */

export function SupportInsights() {
  const toast = useToast();
  const [insights, loadInsights] = useLoad(getInsights);
  const [review, loadReview] = useLoad(listReview);
  const [lessons, loadLessons] = useLoad(useCallback(() => listLessons(), []));
  const [routed, loadRouted] = useLoad(useCallback(() => listRecords(RecordKind.ROUTED), []));
  const [dialog, setDialog] = useState<{ title: string; note: string; text: string } | null>(null);

  const afterReview = () => void Promise.all([loadReview(), loadInsights()]);
  const afterLesson = () => void Promise.all([loadLessons(), loadInsights()]);

  async function exportScenario(id: string) {
    try {
      const call = await getCall(id);
      setDialog({
        title: 'Test scenario',
        note: 'Save as a file in backend/voice/eval/scenarios/ and add the expectations you want the agent to meet.',
        text: scenarioYaml(call),
      });
    } catch (e) {
      toast.error(e);
    }
  }

  return (
    <>
      <div className="page-head">
        <div style={{ display: 'grid', gap: 4 }}>
          <h1>Insights</h1>
          <span className="muted small">How customers rated the agent, what reviewers flagged, and what the agent has learned.</span>
        </div>
      </div>
      {insights.error && <LoadError what="The summary" error={insights.error} retry={() => void loadInsights()} />}
      <Summary insights={insights} />
      <ReviewQueue review={review} reload={afterReview} onExport={(id) => void exportScenario(id)} />
      <LessonsPanel lessons={lessons} reload={afterLesson} />
      <FaqGaps
        routed={routed}
        reload={() => void loadRouted()}
        onShow={(g) => setDialog({ title: 'FAQ draft', note: 'The clipboard is blocked here; copy the draft below.', text: faqDraft(g) })}
      />
      {dialog && <CopyDialog title={dialog.title} note={dialog.note} text={dialog.text} onClose={() => setDialog(null)} />}
    </>
  );
}
