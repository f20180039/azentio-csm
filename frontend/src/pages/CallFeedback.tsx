import { useState } from 'react';
import {
  FeedbackVerdict,
  proposeLesson,
  rateCall,
  RATING_SOURCE_LABEL,
  sendFeedback,
  type CallRating,
  type TurnFeedback,
} from '../api/support';
import { PiiText } from '../components/PiiText';
import { Stars, StarInput } from '../components/Stars';
import { useToast } from '../components/Toasts';
import { displayName } from '../demoUsers';
import { formatDateTime } from '../format';
import { useCanReview } from '../session';
import { LessonLength } from '../vocab';

/* ---------- call rating ---------- */

export function RatingPanel({ callId, rating, ended, onSaved }: { callId: string | null; rating: CallRating | null; ended: boolean; onSaved: () => void }) {
  const toast = useToast();
  const [score, setScore] = useState(0);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!callId || !score) return;
    setBusy(true);
    try {
      await rateCall(callId, score, comment.trim() || null);
      toast.push('Rating saved', `${score} out of 5`);
      onSaved();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel guard-panel" aria-labelledby="rating-title">
      <h2 id="rating-title">Customer rating</h2>
      {rating ? (
        <div className="rating-view">
          <div className="row">
            <Stars score={rating.score} size={20} />
            <span className="num">{rating.score}/5</span>
          </div>
          {rating.comment && (
            <p className="rating-comment">
              “<PiiText text={rating.comment} />”
            </p>
          )}
          <span className="small muted">
            {RATING_SOURCE_LABEL[rating.source] ?? rating.source} · {formatDateTime(rating.at)}
          </span>
        </div>
      ) : !ended ? (
        <p className="small muted">The agent asks the customer for a 1–5 rating before saying goodbye.</p>
      ) : (
        <form
          className="rating-form"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <p className="small muted">The customer did not rate this call. Add the rating they gave you.</p>
          <StarInput value={score} onChange={setScore} disabled={busy} />
          <textarea aria-label="Rating comment (optional)" placeholder="Comment (optional)" rows={2} value={comment} onChange={(e) => setComment(e.target.value)} disabled={busy} />
          <div className="row">
            <button type="submit" className="btn primary sm" disabled={!score || busy}>
              {busy ? 'Saving…' : 'Save rating'}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

/* ---------- agent-turn feedback ---------- */

function FeedbackList({ items }: { items: TurnFeedback[] }) {
  if (!items.length) return null;
  return (
    <ul className="fb-list" aria-label="Reviewer feedback">
      {items.map((f) => (
        <li key={`${f.author}-${f.at}`} className={`fb-item ${f.verdict === FeedbackVerdict.BAD ? 'bad' : 'ok'}`}>
          <div className="row" style={{ gap: 6 }}>
            <span className={`pill ${f.verdict === FeedbackVerdict.BAD ? 'bad' : 'ok'}`}>{f.verdict === FeedbackVerdict.BAD ? '👎 Bad answer' : '👍 Good answer'}</span>
            <span className="small">{displayName(f.author)}</span>
            <time className="small muted" dateTime={f.at}>
              {formatDateTime(f.at)}
            </time>
          </div>
          {f.correction && (
            <p className="fb-correction">
              <span className="small muted">Should have said: </span>
              <PiiText text={f.correction} />
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

export function LessonForm({
  initial = '',
  sourceCallId = null,
  sourceSeq = null,
  onDone,
  onCancel,
  submitLabel = 'Propose lesson',
}: {
  initial?: string;
  sourceCallId?: string | null;
  sourceSeq?: number | null;
  onDone: () => void;
  onCancel?: () => void;
  submitLabel?: string;
}) {
  const toast = useToast();
  const [text, setText] = useState(initial.slice(0, LessonLength.MAX));
  const [busy, setBusy] = useState(false);
  const n = text.trim().length;
  const valid = n >= LessonLength.MIN && n <= LessonLength.MAX;

  async function submit() {
    if (!valid) return;
    setBusy(true);
    try {
      await proposeLesson(text.trim(), sourceCallId, sourceSeq);
      toast.push('Lesson proposed', 'An admin can activate it on the Insights page.');
      setText('');
      onDone();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="lesson-form"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <textarea
        aria-label="Lesson text"
        placeholder="A short instruction the agent should follow on future calls"
        rows={3}
        maxLength={LessonLength.MAX}
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={busy}
      />
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <span className={`small ${n && !valid ? 'bad-text' : 'muted'}`}>
          {n}/{LessonLength.MAX}
          {n > 0 && n < LessonLength.MIN && ` · at least ${LessonLength.MIN} characters`}
        </span>
        <span className="row">
          {onCancel && (
            <button type="button" className="btn ghost sm" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
          )}
          <button type="submit" className="btn primary sm" disabled={!valid || busy}>
            {busy ? 'Saving…' : submitLabel}
          </button>
        </span>
      </div>
    </form>
  );
}

export function TurnFeedbackBlock({ callId, seq, feedback, onChanged }: { callId: string; seq: number; feedback: TurnFeedback[]; onChanged: () => void }) {
  const toast = useToast();
  const canReview = useCanReview();
  const [mode, setMode] = useState<'idle' | 'bad' | 'lesson'>('idle');
  const [correction, setCorrection] = useState('');
  const [busy, setBusy] = useState(false);
  const withCorrection = [...feedback].reverse().find((f) => f.correction);

  async function send(verdict: FeedbackVerdict, text: string | null) {
    setBusy(true);
    try {
      await sendFeedback(callId, seq, verdict, text);
      setMode('idle');
      setCorrection('');
      onChanged();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  }

  if (!canReview && !feedback.length) return null;
  return (
    <div className="fb">
      <FeedbackList items={feedback} />
      {canReview && (
        <div className="row fb-actions">
          <span className="small muted">Was this answer right?</span>
          <button type="button" className="btn ghost sm fb-btn" aria-label="Good answer" title="Good answer" disabled={busy} onClick={() => void send(FeedbackVerdict.GOOD, null)}>
            👍
          </button>
          <button
            type="button"
            className={`btn ghost sm fb-btn${mode === 'bad' ? ' on' : ''}`}
            aria-label="Bad answer"
            title="Bad answer"
            aria-expanded={mode === 'bad'}
            disabled={busy}
            onClick={() => setMode(mode === 'bad' ? 'idle' : 'bad')}
          >
            👎
          </button>
          {withCorrection && mode !== 'lesson' && (
            <button type="button" className="btn sm" onClick={() => setMode('lesson')}>
              Propose a lesson
            </button>
          )}
        </div>
      )}
      {canReview && mode === 'bad' && (
        <form
          className="fb-form"
          onSubmit={(e) => {
            e.preventDefault();
            void send(FeedbackVerdict.BAD, correction.trim() || null);
          }}
        >
          <label className="small" htmlFor={`fb-${callId}-${seq}`}>
            What should it have said?
          </label>
          <textarea id={`fb-${callId}-${seq}`} rows={3} value={correction} onChange={(e) => setCorrection(e.target.value)} disabled={busy} />
          <div className="row">
            <button type="button" className="btn ghost sm" onClick={() => setMode('idle')} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn primary sm" disabled={busy}>
              {busy ? 'Saving…' : 'Save feedback'}
            </button>
          </div>
        </form>
      )}
      {canReview && mode === 'lesson' && withCorrection && (
        <LessonForm initial={withCorrection.correction ?? ''} sourceCallId={callId} sourceSeq={seq} onDone={() => setMode('idle')} onCancel={() => setMode('idle')} />
      )}
    </div>
  );
}
