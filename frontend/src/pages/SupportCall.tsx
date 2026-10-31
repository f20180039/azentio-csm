import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { CustomerCard } from '../components/CustomerCard';
import { SpeakingBubble, speechStatus, useLiveSpeech } from '../components/LiveSpeech';
import { ApiError } from '../api/errors';
import {
  audioDataUrl,
  CHANNEL_LABEL,
  connectSupportVoice,
  getCustomerProfile,
  pauseCall,
  verifiedCustomerRef,
  endCall,
  getCall,
  intentLabel,
  intentTone,
  languageLabel,
  OUTCOME_LABEL,
  simAudio,
  suggestOutcome,
  SUPPORT_OUTCOMES,
  verificationOf,
  type CustomerProfile,
  type SimTurn,
  type SupportCall as SupportCallRecord,
  type SupportOutcome,
  type SupportTurn,
  type ToolTrace,
  turnAudioUrl,
} from '../api/support';
import { getPhoneAllowed, placeSupportPhoneCall, type PhoneAllowed } from '../api/phone';
import type { VoiceSession } from '../api/voice';
import { NoResults, SearchBox, useUrlQuery } from '../components/SearchBox';
import { Select } from '../components/Select';
import { useToast } from '../components/Toasts';
import { formatDateTime, formatInr, humanise, intentSourceLabel } from '../format';
import { Route } from '../routes';
import { Highlight, turnMatches } from '../search';
import { SpeechLanguage, TurnRole, Verification } from '../vocab';
import { RatingPanel, TurnFeedbackBlock } from './CallFeedback';
import { CallStatusPill } from './SupportDesk';

const POLL_MS = 1000;
const MONEY_KEY = /amount|balance|premium|principal|sum_insured/i;

/* ---------- small pieces ---------- */

export function VerificationBadge({ call }: { call: Pick<SupportCallRecord, 'turns' | 'verified'> | null }) {
  const { state, failures } = call ? verificationOf(call) : { state: Verification.NOT_VERIFIED, failures: 0 };
  const tone = state === Verification.VERIFIED ? 'ok' : state === Verification.LOCKED ? 'bad' : failures > 0 ? 'warn' : 'dim';
  const label = state === Verification.VERIFIED ? 'Verified' : state === Verification.LOCKED ? 'Locked' : 'Not verified';
  const note =
    state === Verification.LOCKED
      ? 'Three failed checks: personal data stays closed for 15 minutes.'
      : state === Verification.NOT_VERIFIED && failures > 0
        ? `${failures} failed check${failures > 1 ? 's' : ''}`
        : undefined;
  return (
    <span className={`pill ${tone} sc-badge`} data-testid="verification" data-state={state} title={note}>
      <span className="dot" aria-hidden="true" />
      {label}
      {note && state !== Verification.LOCKED && <span className="sc-badge-note">· {note}</span>}
    </span>
  );
}

function IntentChips({ intents, query = '' }: { intents: string[]; query?: string }) {
  if (!intents.length) return null;
  return (
    <ul className="sc-chips" aria-label="Identified intents">
      {intents.map((i) => (
        <li key={i}>
          <span className={`pill ${intentTone(i)}`} title={i}>
            <Highlight text={intentLabel(i)} query={query} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function Scalar({ k, v }: { k: string; v: unknown }) {
  if (v === null || v === undefined || v === '') return <span className="muted">—</span>;
  if (typeof v === 'number' && MONEY_KEY.test(k)) return <span className="num">{formatInr(v)}</span>;
  if (typeof v === 'boolean') return <span>{v ? 'Yes' : 'No'}</span>;
  if (typeof v === 'number') return <span className="num">{v}</span>;
  return <span>{String(v)}</span>;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v);
}

/** Renders a tool result the way an operator reads it: field names and stored values, lists as tables. */
function Fields({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="muted small">No records returned</span>;
    if (value.every(isRecord)) {
      const cols = [...new Set(value.flatMap((r) => Object.keys(r)))].slice(0, 8);
      return (
        <div className="table-wrap sc-mini">
          <table>
            <thead>
              <tr>
                {cols.map((c) => (
                  <th key={c}>{humanise(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {value.map((r, i) => (
                <tr key={i}>
                  {cols.map((c) => (
                    <td key={c}>{isRecord(r[c]) ? <Fields value={r[c]} depth={depth + 1} /> : <Scalar k={c} v={r[c]} />}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return <span>{value.map(String).join(', ')}</span>;
  }
  if (isRecord(value)) {
    if (depth > 2) return <code className="small">{JSON.stringify(value)}</code>;
    return (
      <dl className="facts sc-fields">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="sc-field">
            <dt>{humanise(k)}</dt>
            <dd>{isRecord(v) || Array.isArray(v) ? <Fields value={v} depth={depth + 1} /> : <Scalar k={k} v={v} />}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return <Scalar k="" v={value} />;
}

function argText(args: Record<string, unknown> | undefined): string {
  return Object.entries(args ?? {})
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' · ');
}

export function RetrievedCard({ trace, retrieved, refs }: { trace: ToolTrace[]; retrieved: Record<string, unknown>; refs: string[] }) {
  const traced = new Set(trace.map((t) => t.name));
  const extra = Object.keys(retrieved).filter((k) => !traced.has(k));
  const count = trace.length + extra.length;
  return (
    <details className="sc-retrieved">
      <summary>
        Retrieved <span className="muted">· {count ? `${count} tool call${count > 1 ? 's' : ''}` : 'no tools used'}</span>
      </summary>
      <div className="sc-retrieved-body">
        {count === 0 && <span className="small muted">This reply did not read any bank system.</span>}
        {trace.map((t, i) => (
          <div key={`${t.name}-${i}`} className="sc-tool">
            <div className="sc-tool-head">
              <code className="sc-tool-name">{t.name}</code>
              {argText(t.args) && <span className="mono small muted">{argText(t.args)}</span>}
            </div>
            {t.result_summary && <div className="small">{t.result_summary}</div>}
            {retrieved[t.name] !== undefined && <Fields value={retrieved[t.name]} />}
          </div>
        ))}
        {extra.map((k) => (
          <div key={k} className="sc-tool">
            <code className="sc-tool-name">{k}</code>
            <Fields value={retrieved[k]} />
          </div>
        ))}
        <details className="sc-raw">
          <summary className="small">Raw JSON</summary>
          <pre>{JSON.stringify({ tool_trace: trace, retrieved, refs }, null, 2)}</pre>
        </details>
      </div>
    </details>
  );
}

function RefPills({ refs, query = '' }: { refs: string[]; query?: string }) {
  if (!refs.length) return null;
  return (
    <ul className="sc-chips" aria-label="References">
      {refs.map((r) => (
        <li key={r}>
          <span className="ref-pill">
            <Highlight text={r} query={query} />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The language chip of a translated (Kannada or Hindi) turn; nothing for an English one. */
function LanguageChip({ meta }: { meta: SupportTurn['meta'] }) {
  if (!meta.text_en) return null;
  return (
    <span className="pill dim sc-lang">
      {languageLabel(meta.language)}
    </span>
  );
}

/**
 * A turn's words. A translated turn shows two lines: the original (the record) and its English; "English first" swaps
 * which one is prominent. The secondary line is small, muted and labelled with its language.
 */
function TurnText({ t, query, englishFirst }: { t: SupportTurn; query: string; englishFirst: boolean }) {
  const m = t.meta;
  if (!m.text_en) {
    return (
      <p lang={m.language}>
        <Highlight text={t.text} query={query} />
      </p>
    );
  }
  const original = { text: t.text, lang: m.language, label: languageLabel(m.language), testId: 'turn-original' };
  const english = { text: m.text_en, lang: SpeechLanguage.ENGLISH, label: languageLabel(SpeechLanguage.ENGLISH), testId: 'turn-english' };
  const [first, second] = englishFirst ? [english, original] : [original, english];
  return (
    <>
      <p lang={first.lang} data-testid={first.testId}>
        <Highlight text={first.text} query={query} />
      </p>
      <p lang={second.lang} data-testid={second.testId} className="small muted sc-turn-alt">
        <span className="sc-turn-alt-label">{second.label}:</span> <Highlight text={second.text} query={query} />
      </p>
    </>
  );
}

type TurnMark = 'hit' | 'dim' | undefined;

function Turn({ t, audio, query = '', mark, callId, onChanged, englishFirst = false }: { t: SupportTurn; audio?: string | null; query?: string; mark?: TurnMark; callId?: string | null; onChanged?: () => void; englishFirst?: boolean }) {
  const m = t.meta;
  const markClass = mark ? ` is-${mark}` : '';
  if (t.role === TurnRole.CUSTOMER) {
    return (
      <li className={`sc-turn customer${markClass}`} data-search={mark}>
        <div className="sc-turn-head">
          <span className="who">Customer</span>
          <LanguageChip meta={m} />
          <time className="small muted" dateTime={t.at}>
            {formatDateTime(t.at)}
          </time>
        </div>
        {m.no_speech ? <p className="muted sc-nospeech">No speech detected</p> : <TurnText t={t} query={query} englishFirst={englishFirst} />}
        {m.audio && callId && (
          <audio controls preload="none" src={turnAudioUrl(callId, t.seq)} aria-label="What the customer said" className="sc-audio" />
        )}
        <div className="row" style={{ gap: 6 }}>
          <IntentChips intents={m.intents ?? []} query={query} />
          {m.intent_source && <span className="small muted">via {intentSourceLabel(m.intent_source)}</span>}
          {m.locked ? (
            <span className="pill bad">Locked</span>
          ) : (m.verify_failures ?? 0) > 0 && !m.verified ? (
            <span className="pill warn">
              {m.verify_failures} failed check{(m.verify_failures ?? 0) > 1 ? 's' : ''}
            </span>
          ) : null}
        </div>
      </li>
    );
  }
  return (
    <li className={`sc-turn agent${markClass}`} data-search={mark}>
      <div className="sc-turn-head">
        <span className="who">Agent</span>
        <LanguageChip meta={m} />
        <time className="small muted" dateTime={t.at}>
          {formatDateTime(t.at)}
        </time>
      </div>
      <TurnText t={t} query={query} englishFirst={englishFirst} />
      <RefPills refs={m.refs ?? []} query={query} />
      {audio && <audio controls src={audioDataUrl(audio)} aria-label="Agent reply audio" className="sc-audio" />}
      <RetrievedCard trace={m.tool_trace ?? []} retrieved={m.retrieved ?? {}} refs={m.refs ?? []} />
      {callId && onChanged && <TurnFeedbackBlock callId={callId} seq={t.seq} feedback={t.feedback ?? []} onChanged={onChanged} />}
    </li>
  );
}

/** Builds timeline turns from /sim/audio results, for when the call record has not caught up yet. */
function turnsFromSim(results: SimTurn[]): SupportTurn[] {
  const now = new Date().toISOString();
  const out: SupportTurn[] = [];
  for (const r of results) {
    out.push({
      seq: out.length + 1, role: TurnRole.CUSTOMER, text: r.transcript, at: now,
      meta: { intents: r.intents, verified: r.verified, no_speech: r.no_speech },
    });
    if (r.reply_text) {
      const refs = [...new Set(JSON.stringify(r.retrieved ?? {}).match(/\b(?:SR|CMP|RQ|ESC)-\d{5}\b/g) ?? [])];
      out.push({ seq: out.length + 1, role: TurnRole.AGENT, text: r.reply_text, at: now, meta: { tool_trace: r.tool_trace, retrieved: r.retrieved, refs } });
    }
  }
  return out;
}

/* ---------- end dialog ---------- */

function EndDialog({ initial, busy, onCancel, onConfirm }: { initial: SupportOutcome; busy: boolean; onCancel: () => void; onConfirm: (o: SupportOutcome) => void }) {
  const [outcome, setOutcome] = useState<SupportOutcome>(initial);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => first.current?.focus(), []);
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') onCancel();
  };
  return (
    <div className="overlay" onKeyDown={onKey}>
      <form
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="end-title"
        onSubmit={(e) => {
          e.preventDefault();
          onConfirm(outcome);
        }}
      >
        <h2 id="end-title">End this call</h2>
        <fieldset className="sc-outcomes">
          <legend className="small muted">How did the call end?</legend>
          {SUPPORT_OUTCOMES.map((o) => (
            <label key={o} className={`sc-outcome${outcome === o ? ' on' : ''}`}>
              <input
                ref={o === outcome ? first : undefined}
                type="radio"
                name="outcome"
                value={o}
                checked={outcome === o}
                onChange={() => setOutcome(o)}
              />
              {OUTCOME_LABEL[o]}
              {o === initial && <span className="small muted"> (suggested)</span>}
            </label>
          ))}
        </fieldset>
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            Keep the call open
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? 'Ending…' : 'End call'}
          </button>
        </div>
      </form>
    </div>
  );
}

/* ---------- input modes ---------- */

type Mode = 'mic' | 'upload';

interface UploadProps {
  callId: string | null;
  disabled: boolean;
  onCallId: (id: string) => void;
  onResults: (r: SimTurn[]) => void;
  results: SimTurn[];
}

function UploadPanel({ callId, disabled, onCallId, onResults, results }: UploadProps) {
  const toast = useToast();
  const [files, setFiles] = useState<File[]>([]);
  const [drag, setDrag] = useState(false);
  const [sending, setSending] = useState<{ done: number; total: number; name: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const player = useRef<HTMLAudioElement>(null);

  const add = (list: FileList | null) => {
    if (!list) return;
    const audio = [...list].filter((f) => !f.type || f.type.startsWith('audio/') || /\.(wav|mp3|m4a|ogg|webm|flac)$/i.test(f.name));
    if (audio.length < list.length) toast.push('Some files were skipped', 'Only audio files can be sent.', 'warn');
    setFiles((f) => [...f, ...audio]);
  };
  const move = (i: number, d: number) =>
    setFiles((f) => {
      const n = [...f];
      const j = i + d;
      if (j < 0 || j >= n.length) return f;
      [n[i], n[j]] = [n[j], n[i]];
      return n;
    });

  async function send() {
    let id = callId;
    const collected: SimTurn[] = [];
    setSending({ done: 0, total: files.length, name: files[0]?.name ?? '' });
    try {
      for (let i = 0; i < files.length; i++) {
        setSending({ done: i, total: files.length, name: files[i].name });
        const r = await simAudio([files[i]], id ?? undefined);
        if (!id) {
          id = r.call_id;
          onCallId(r.call_id);
        }
        collected.push(...r.turns);
        onResults([...results, ...collected]);
      }
      setFiles([]);
    } catch (e) {
      toast.error(e);
    } finally {
      setSending(null);
    }
  }

  function playAll() {
    const queue = results.filter((r) => r.reply_audio_b64).map((r) => audioDataUrl(r.reply_audio_b64!));
    const el = player.current;
    if (!el || !queue.length) return;
    let i = 0;
    el.onended = () => {
      i += 1;
      if (i < queue.length) {
        el.src = queue[i];
        void el.play().catch(() => undefined);
      }
    };
    el.src = queue[0];
    void el.play().catch(() => undefined);
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    if (!disabled && !sending) add(e.dataTransfer.files);
  };
  const busy = !!sending;
  const withAudio = results.filter((r) => r.reply_audio_b64).length;

  return (
    <div className="sc-mode-body">
      <label
        className={`dropzone${drag ? ' active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <svg className="dropzone-icon" viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M9 18V6l10-2v12M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3zm10-2a3 3 0 1 1-3-3 3 3 0 0 1 3 3z" />
        </svg>
        <strong>Drop audio files here</strong>
        <span className="small">One file per customer turn, sent in the order listed.</span>
        <span className="btn sm dropzone-btn" aria-hidden="true">
          Choose files
        </span>
        <input
          ref={input}
          type="file"
          accept="audio/*"
          multiple
          className="sr-only"
          aria-label="Choose audio files"
          disabled={disabled || busy}
          onChange={(e) => {
            add(e.target.files);
            e.target.value = '';
          }}
        />
      </label>
      {files.length > 0 && (
        <ol className="sc-files" aria-label="Files to send">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`}>
              <span className="num muted">{i + 1}.</span>
              <span className="sc-file-name">{f.name}</span>
              <span className="row" style={{ gap: 2 }}>
                <button type="button" className="btn ghost sm" onClick={() => move(i, -1)} disabled={i === 0 || busy} aria-label={`Move ${f.name} up`}>
                  ↑
                </button>
                <button type="button" className="btn ghost sm" onClick={() => move(i, 1)} disabled={i === files.length - 1 || busy} aria-label={`Move ${f.name} down`}>
                  ↓
                </button>
                <button type="button" className="btn ghost sm" onClick={() => setFiles((l) => l.filter((_, j) => j !== i))} disabled={busy} aria-label={`Remove ${f.name}`}>
                  ✕
                </button>
              </span>
            </li>
          ))}
        </ol>
      )}
      <div className="row">
        <button type="button" className="btn primary" onClick={send} disabled={disabled || busy || files.length === 0}>
          {busy ? 'Sending…' : files.length ? `Send ${files.length} file${files.length > 1 ? 's' : ''}` : 'Send'}
        </button>
        {withAudio > 0 && (
          <button type="button" className="btn" onClick={playAll} disabled={busy}>
            Play replies in order
          </button>
        )}
      </div>
      {sending && (
        <div className="sc-progress" role="status">
          <span className="small">
            Sending {sending.done + 1} of {sending.total}: <span className="mono">{sending.name}</span>
          </span>
          <progress max={sending.total} value={sending.done} aria-label="Upload progress" />
        </div>
      )}
      <audio ref={player} className="sr-only" aria-hidden="true" />
      {results.length > 0 && (
        <ol className="sc-results" aria-label="Processed files">
          {results.map((r, i) => (
            <li key={`${r.file}-${i}`}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <span className="mono small">{r.file}</span>
                {r.no_speech ? <span className="pill dim">No speech detected</span> : <IntentChips intents={r.intents} />}
              </div>
              {!r.no_speech && <p className="small">“{r.transcript}”</p>}
              {r.reply_text && <p className="small muted">Agent: {r.reply_text}</p>}
              {r.reply_audio_b64 && <audio controls src={audioDataUrl(r.reply_audio_b64)} aria-label={`Reply to ${r.file}`} className="sc-audio" />}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** "Call a phone": the desk rings an allowed number and the answered call becomes this support call. Shown only when
 * the voice service has Twilio set up; the browser only ever sees masked numbers. */
function PhoneDial({ onCallId }: { onCallId: (id: string) => void }) {
  const toast = useToast();
  const [allowed, setAllowed] = useState<PhoneAllowed>({ configured: false, numbers: [] });
  const [numberId, setNumberId] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    void getPhoneAllowed().then((a) => {
      if (!live) return;
      setAllowed(a);
      setNumberId(a.numbers[0]?.id ?? '');
    });
    return () => {
      live = false;
    };
  }, []);

  if (!allowed.configured) return null;

  async function dial() {
    setBusy(true);
    try {
      const { call_id } = await placeSupportPhoneCall(numberId);
      toast.push('Phone ringing', 'Answer it to talk to the agent; turns appear here.');
      onCallId(call_id);
    } catch (e) {
      toast.push('Could not place the phone call', e instanceof Error ? e.message : String(e), 'bad');
      setBusy(false);
    }
  }

  return (
    <div className="row sc-phone-dial">
      <Select
        aria-label="Phone number"
        value={numberId}
        onChange={setNumberId}
        disabled={busy}
        options={allowed.numbers.map((n) => ({ value: n.id, label: n.masked }))}
      />
      <button className="btn" onClick={dial} disabled={busy || !numberId}>
        {busy ? 'Dialling…' : 'Call a phone'}
      </button>
    </div>
  );
}

/* ---------- the page ---------- */

export function SupportCall() {
  const { callId: routeId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;

  const [createdId, setCreatedId] = useState<string | null>(null);
  const callId = routeId ?? createdId;
  const [call, setCall] = useState<SupportCallRecord | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>('mic');
  const [voice, setVoice] = useState<'off' | 'connecting' | 'on'>('off');
  const [paused, setPaused] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [results, setResults] = useState<SimTurn[]>(() => (location.state as { results?: SimTurn[] } | null)?.results ?? []);
  const [ending, setEnding] = useState<'closed' | 'open' | 'busy'>('closed');
  const session = useRef<VoiceSession | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<HTMLOListElement>(null);
  const pollFailed = useRef(false);
  const unmounted = useRef(false);

  const ended = !!call?.endedAt;

  const refresh = useCallback(async () => {
    if (!callId) return;
    try {
      const c = await getCall(callId);
      if (unmounted.current) return;
      setCall(c);
      setLoadError(null);
      pollFailed.current = false;
    } catch (e) {
      if (unmounted.current) return;
      if (!pollFailed.current) toastRef.current.error(e);
      pollFailed.current = true;
      setLoadError(e instanceof ApiError && e.status === 404 ? 'This call does not exist.' : e instanceof Error ? e.message : String(e));
    }
  }, [callId]);

  useEffect(() => {
    if (!callId) return;
    void refresh();
    if (ended) return;
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [callId, ended, refresh]);

  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
      void session.current?.disconnect().catch(() => undefined);
    };
  }, []);

  useEffect(() => {
    if (!ended) return;
    const s = session.current;
    session.current = null;
    setVoice('off');
    setPaused(false);
    void s?.disconnect().catch(() => undefined);
  }, [ended]);

  const adopt = useCallback(
    (id: string, state?: { results: SimTurn[] }) => {
      setCreatedId(id);
      // a mic call from a page already showing a call is a new call (the voice service never reattaches), so follow it
      if (id !== routeId) navigate(Route.supportCall(id), { replace: !routeId, state });
    },
    [navigate, routeId],
  );

  const turns: SupportTurn[] = call?.turns.length ? call.turns : turnsFromSim(results);
  const speech = useLiveSpeech(voice === 'on' && !paused, audio, timelineRef);

  // the verified caller's bank profile; refetched as turns arrive, so records raised on this call show up
  const customerRef = verifiedCustomerRef(turns);
  const [profile, setProfile] = useState<CustomerProfile | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  useEffect(() => {
    if (!customerRef) {
      setProfile(null);
      return;
    }
    let stale = false;
    getCustomerProfile(customerRef)
      .then((p) => {
        if (stale) return;
        setProfile(p);
        setProfileError(null);
      })
      .catch((e: unknown) => {
        if (!stale) setProfileError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      stale = true;
    };
  }, [customerRef, turns.length]);
  const speaking = speech.customer ? 'customer' : speech.agent ? 'agent' : null;
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' });
  }, [turns.length, speaking]);

  const [query, setQuery] = useUrlQuery();
  const searching = query.trim() !== '';
  /** "English first" for Kannada and Hindi turns; this page's state only, offered once a turn carries an English translation. */
  const [englishFirst, setEnglishFirst] = useState(false);
  const translated = turns.some((t) => t.meta.text_en);
  const hits = useMemo(() => new Set(searching ? turns.filter((t) => turnMatches(query, t)) : []), [turns, query, searching]);
  useEffect(() => {
    if (searching) timelineRef.current?.querySelector('[data-search="hit"]')?.scrollIntoView?.({ block: 'nearest' });
  }, [query, searching]);

  const audioByReply = new Map(results.filter((r) => r.reply_text && r.reply_audio_b64).map((r) => [r.reply_text!, r.reply_audio_b64!]));

  async function startMic() {
    setVoice('connecting');
    try {
      const s = await connectSupportVoice(callId ?? undefined, audio.current, {
        onCallId: (id) => {
          if (id !== callId) adopt(id);
        },
        onDisconnected: () => {
          if (unmounted.current) return;
          setVoice('off');
          setPaused(false);
        },
        onError: (m) => toastRef.current.push('Voice connection problem', m, 'warn'),
      });
      if (unmounted.current) {
        void s.disconnect().catch(() => undefined);
        return;
      }
      session.current = s;
      setVoice('on');
    } catch (e) {
      if (unmounted.current) return;
      setVoice('off');
      toast.push('Could not start the microphone call', e instanceof Error ? e.message : 'Check the voice service and microphone permission.', 'bad');
    }
  }

  async function stopMic() {
    const s = session.current;
    session.current = null;
    await s?.disconnect().catch(() => undefined);
    setVoice('off');
    setPaused(false);
  }

  /** Side talk during a demo: the mic is muted first, so nothing said while paused reaches the agent. */
  async function togglePause() {
    const s = session.current;
    if (!s || !callId) return;
    const next = !paused;
    setPausing(true);
    try {
      if (next) s.setMicEnabled?.(false);
      await pauseCall(callId, next);
      if (!next) s.setMicEnabled?.(true);
      setPaused(next);
    } catch (e) {
      s.setMicEnabled?.(!paused);
      toast.error(e);
    } finally {
      setPausing(false);
    }
  }

  async function finish(outcome: SupportOutcome) {
    if (!callId) return;
    setEnding('busy');
    try {
      await endCall(callId, outcome);
    } catch (e) {
      if (!(e instanceof ApiError && (e.status === 409 || e.detail === 'CALL_ALREADY_ENDED'))) {
        toast.error(e);
        setEnding('open');
        return;
      }
    }
    try {
      await stopMic();
      await refresh();
      setEnding('closed');
      toast.push('Call ended', call?.outcome ? OUTCOME_LABEL[call.outcome] : OUTCOME_LABEL[outcome]);
    } catch (e) {
      toast.error(e);
      setEnding('closed');
    }
  }

  if (routeId && loadError && !call && results.length === 0) {
    return (
      <div className="empty" role="alert">
        <strong>This call could not be loaded</strong>
        <span>{loadError}</span>
        <div className="row">
          <button className="btn" onClick={() => void refresh()}>
            Retry
          </button>
          <Link to={Route.SUPPORT}>Back to the desk</Link>
        </div>
      </div>
    );
  }
  if (routeId && !call && results.length === 0) return <p className="muted">Loading call…</p>;

  const intentsSeen = [...new Set(turns.flatMap((t) => (t.role === TurnRole.CUSTOMER ? t.meta.intents ?? [] : [])))];
  const refsSeen = [...new Set(turns.flatMap((t) => t.meta.refs ?? []))];
  const toolCount = turns.reduce((n, t) => n + (t.meta.tool_trace?.length ?? 0), 0);
  const badgeSource = call ?? { turns, verified: false };

  return (
    <>
      <div className="case-head">
        <Link to={Route.SUPPORT} className="small">
          ← Customer service desk
        </Link>
        <div className="page-head">
          <div style={{ display: 'grid', gap: 6 }}>
            <h1>{callId ? 'Support call' : 'New support call'}</h1>
            <div className="case-meta">
              <VerificationBadge call={badgeSource} />
              {call ? (
                <CallStatusPill c={call} />
              ) : (
                <span className="pill dim">
                  <span className="dot" aria-hidden="true" />
                  Not started
                </span>
              )}
              {voice === 'on' && (
                <span className="pill info pulse">
                  <span className="dot" aria-hidden="true" />
                  Microphone live
                </span>
              )}
              {callId && <span className="mono small muted">{callId}</span>}
            </div>
          </div>
          {callId && !ended && (
            <button className="btn danger" onClick={() => setEnding('open')} disabled={ending !== 'closed'}>
              End call
            </button>
          )}
        </div>
      </div>

      <audio ref={audio} autoPlay />

      <div className="call-grid">
        <section className="panel" aria-labelledby="timeline-title">
          <h2 id="timeline-title" className="panel-title">
            Conversation
          </h2>
          {turns.length > 0 && (
            <div className="search-bar">
              <SearchBox
                value={query}
                onChange={setQuery}
                label="Search the conversation"
                placeholder="Search the transcript, intents or references"
                shown={hits.size}
                total={turns.length}
              />
              {translated && (
                <label className="sc-english-first small">
                  <input type="checkbox" role="switch" checked={englishFirst} onChange={(e) => setEnglishFirst(e.target.checked)} />
                  English first
                </label>
              )}
            </div>
          )}
          {searching && turns.length > 0 && hits.size === 0 && <NoResults query={query} onClear={() => setQuery('')} />}
          <ol ref={timelineRef} className="sc-timeline" role="log" aria-live="polite" aria-label="Conversation history">
            {turns.map((t) => (
              <Turn
                key={`${t.role}-${t.seq}`}
                t={t}
                audio={t.role === TurnRole.AGENT ? audioByReply.get(t.text) : null}
                query={query}
                mark={searching ? (hits.has(t) ? 'hit' : 'dim') : undefined}
                callId={call?.turns.length ? call.id : null}
                onChanged={() => void refresh()}
                englishFirst={englishFirst}
              />
            ))}
            {speaking && <SpeakingBubble who={speaking} />}
          </ol>
          {turns.length === 0 && !speaking && (
            <div className="empty">
              <strong>No conversation yet</strong>
              <span>{callId ? 'Turns appear here as the customer speaks.' : 'Start the microphone or send recorded audio to begin.'}</span>
            </div>
          )}
          <div ref={endRef} />
        </section>

        <aside style={{ display: 'grid', gap: 12, alignContent: 'start' }}>
          <section className="panel guard-panel" aria-labelledby="input-title">
            <h2 id="input-title">Customer audio</h2>
            {ended ? (
              <p className="small muted">This call has ended. Start a new call from the desk.</p>
            ) : (
              <>
                <div className="tabs" role="tablist" aria-label="Input mode">
                  {(['mic', 'upload'] as const).map((m) => (
                    <button
                      key={m}
                      role="tab"
                      id={`mode-${m}`}
                      aria-selected={mode === m}
                      aria-controls={`mode-panel-${m}`}
                      onClick={() => setMode(m)}
                      disabled={voice !== 'off' && m === 'upload'}
                    >
                      {m === 'mic' ? 'Microphone' : 'Upload audio'}
                    </button>
                  ))}
                </div>
                {mode === 'mic' ? (
                  <div id="mode-panel-mic" role="tabpanel" aria-labelledby="mode-mic" className="sc-mode-body">
                    <p className="small muted">Talk to the agent through this browser. Its replies play through your speakers.</p>
                    <p className={`sc-mic-status${speaking ? ' active' : ''}`} role="status">
                      <span className="dot" aria-hidden="true" />
                      {speechStatus(voice === 'on', speech, paused)}
                    </p>
                    <div className="row">
                      {voice === 'off' && (
                        <button className="btn primary" onClick={startMic}>
                          {callId ? 'Reconnect microphone' : 'Start talking'}
                        </button>
                      )}
                      {voice === 'connecting' && (
                        <button className="btn" disabled>
                          Connecting…
                        </button>
                      )}
                      {voice === 'on' && (
                        <>
                          <button className="btn" onClick={() => void togglePause()} disabled={pausing || !callId} aria-pressed={paused}>
                            {paused ? 'Resume' : 'Pause'}
                          </button>
                          <button className="btn" onClick={() => void stopMic()}>
                            Stop
                          </button>
                        </>
                      )}
                    </div>
                    {!callId && voice === 'off' && <PhoneDial onCallId={(id) => adopt(id)} />}
                  </div>
                ) : (
                  <div id="mode-panel-upload" role="tabpanel" aria-labelledby="mode-upload">
                    <UploadPanel
                      callId={callId}
                      disabled={ended}
                      results={results}
                      onResults={setResults}
                      onCallId={(id) => adopt(id)}
                    />
                  </div>
                )}
              </>
            )}
          </section>

          {call && <RatingPanel callId={call.id} rating={call.rating ?? null} ended={ended} onSaved={() => void refresh()} />}

          <section className="panel guard-panel" aria-labelledby="customer-title">
            <h2 id="customer-title">Customer</h2>
            {!customerRef ? (
              <p className="small muted">Shows the caller's bank details once the agent has verified them.</p>
            ) : profile?.customer.customer_ref === customerRef ? (
              <CustomerCard profile={profile} />
            ) : profileError ? (
              <p className="small muted">
                Verified as <span className="mono">{customerRef}</span>; details unavailable ({profileError}).
              </p>
            ) : (
              <p className="small muted">Loading {customerRef}…</p>
            )}
          </section>

          <section className="panel guard-panel" aria-labelledby="facts-title">
            <h2 id="facts-title">Call details</h2>
            <dl className="facts">
              <dt>Channel</dt>
              <dd>{call ? CHANNEL_LABEL[call.channel] ?? humanise(call.channel) : '—'}</dd>
              <dt>Started</dt>
              <dd className="num">{call ? formatDateTime(call.startedAt) : '—'}</dd>
              {call?.endedAt && (
                <>
                  <dt>Ended</dt>
                  <dd className="num">{formatDateTime(call.endedAt)}</dd>
                </>
              )}
              <dt>Intents</dt>
              <dd>{intentsSeen.length ? <IntentChips intents={intentsSeen} /> : '—'}</dd>
              <dt>References</dt>
              <dd>{refsSeen.length ? <RefPills refs={refsSeen} /> : '—'}</dd>
              <dt>Tool calls</dt>
              <dd className="num">{toolCount}</dd>
            </dl>
          </section>
        </aside>
      </div>

      {ending !== 'closed' && call && (
        <EndDialog initial={suggestOutcome(call)} busy={ending === 'busy'} onCancel={() => setEnding('closed')} onConfirm={(o) => void finish(o)} />
      )}
    </>
  );
}
