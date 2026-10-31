import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { endCall, getCall, textCall, textTurn } from '../api/renewals';
import type { CallOutcome, CallView, CaseDetail, TranscriptTurn } from '../api/types';
import { getPhoneAllowed, placePhoneCall, type PhoneAllowed } from '../api/phone';
import { connectVoice, type VoiceSession } from '../api/voice';
import { Select } from '../components/Select';
import { useToast } from '../components/Toasts';
import { formatCallback, formatInr } from '../format';
import { useCallPolling } from '../hooks/useCallPolling';
import { useSession } from '../session';
import { Route } from '../routes';
import { CallOutcome as Outcome, CallTurnRole, Role } from '../vocab';
import { AuditTab, CaseActions } from './CaseWorkspace';

/** The voice service forgets an unanswered dial after this long (its PENDING_TTL_SECS), so a page stops waiting for it too. */
export const PHONE_RING_TIMEOUT_MS = 120_000;
export const PHONE_END_HINT = 'Hang up on the phone (or let the agent end the call)';

export const OUTCOME_LABEL: Record<CallOutcome, string> = {
  [Outcome.HANDED_OFF]: 'Handed to a person',
  [Outcome.RENEWAL_PENDING_PAYMENT]: 'Renewed with changes · payment pending',
  [Outcome.NO_DECISION]: 'No decision',
};
const OUTCOME_TONE: Record<CallOutcome, string> = {
  [Outcome.HANDED_OFF]: 'warn',
  [Outcome.RENEWAL_PENDING_PAYMENT]: 'ok',
  [Outcome.NO_DECISION]: 'dim',
};

type GuardState = 'idle' | 'ok' | 'warn' | 'bad';
interface Guard {
  key: string;
  label: string;
  state: GuardState;
  note: string;
}

export function guardrails(c: CallView | null): Guard[] {
  if (!c) return [];
  const failedHandoff = c.mustHandoff && !c.identityVerified && c.verifyFailures > 0;
  const identity: Guard = c.identityVerified
    ? { key: 'identity', label: 'Identity verified', state: 'ok', note: 'Date of birth matched before any policy detail.' }
    : failedHandoff
      ? { key: 'identity', label: 'Identity verified', state: 'bad', note: `${c.verifyFailures} failed checks: the agent must hand off.` }
      : c.verifyFailures > 0
        ? { key: 'identity', label: 'Identity verified', state: 'warn', note: `${c.verifyFailures} failed check${c.verifyFailures > 1 ? 's' : ''}; not verified yet.` }
        : { key: 'identity', label: 'Identity verified', state: 'idle', note: 'Not yet asked.' };
  const disclosed = c.transcript.some((t) => t.role === CallTurnRole.AGENT);
  return [
    {
      key: 'disclosure',
      label: 'Recording disclosed',
      state: disclosed ? 'ok' : 'idle',
      note: disclosed ? 'Opened with the recording disclosure.' : 'Waiting for the first agent turn.',
    },
    identity,
    c.outOfPlaybookRequests > 0
      ? { key: 'playbook', label: 'Offers within playbook', state: 'warn', note: `${c.outOfPlaybookRequests} out-of-playbook request${c.outOfPlaybookRequests > 1 ? 's' : ''}, refused by the API.` }
      : { key: 'playbook', label: 'Offers within playbook', state: 'ok', note: 'Every quote came from the API.' },
    c.mustHandoff
      ? { key: 'handoff', label: 'Handoff', state: 'bad', note: c.handoffReason ? `Handed off: ${c.handoffReason}` : 'The agent must hand this call to a person.' }
      : { key: 'handoff', label: 'Handoff', state: 'idle', note: 'Not needed so far.' },
  ];
}

function mergeTranscript(server: TranscriptTurn[], live: TranscriptTurn[]): TranscriptTurn[] {
  return server.length >= live.length ? server : live;
}

function Facts({ call }: { call: CallView }) {
  const q = call.lastQuote;
  return (
    <dl className="facts">
      <dt>Policy</dt>
      <dd className="mono">{call.policyId}</dd>
      <dt>Quote</dt>
      <dd className="num">
        {q?.annualPremium != null
          ? `${formatInr(q.annualPremium)} a year${q.instalments && q.instalments > 1 ? ` · ${q.instalments} × ${formatInr(q.perInstalment)}` : ''}`
          : '—'}
      </dd>
      <dt>Payment link</dt>
      <dd data-testid="guard-links">{call.paymentLinkSent ? 'Sent to the mobile on file' : 'Not sent'}</dd>
      <dt>Callback</dt>
      <dd>{call.callbackAt ? formatCallback(call.callbackAt) : '—'}</dd>
    </dl>
  );
}

export function Call() {
  const { callId = '' } = useParams();
  const { can } = useSession();
  const toast = useToast();
  const [call, setCall] = useState<CallView | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [outcome, setOutcome] = useState<CallOutcome | null>(null);
  const [live, setLive] = useState<TranscriptTurn[]>([]);
  const [voice, setVoice] = useState<'off' | 'connecting' | 'on'>('off');
  const [typed, setTyped] = useState('');
  const [sending, setSending] = useState(false);
  const [ending, setEnding] = useState(false);
  const [kase, setKase] = useState<CaseDetail | null>(null);
  const [phoneAllowed, setPhoneAllowed] = useState<PhoneAllowed>({ configured: false, numbers: [] });
  const [phoneNumber, setPhoneNumber] = useState('');
  const [phone, setPhone] = useState<'off' | 'dialling' | 'ringing' | 'live'>('off');
  const turnsAtDial = useRef(0);
  const session = useRef<VoiceSession | null>(null);
  const textStarted = useRef(false);
  const audio = useRef<HTMLAudioElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const pollError = useRef(false);
  const loaded = useRef(false);
  const unmounted = useRef(false);

  /** Fetches the call; `false` when it could not be (one toast per run of failures, and the poller backs off). */
  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const c = await getCall(callId);
      setCall(c);
      loaded.current = true;
      if (c.outcome) setOutcome(c.outcome);
      pollError.current = false;
      return true;
    } catch (e) {
      if (!pollError.current) toast.error(e);
      pollError.current = true;
      if (!loaded.current) setNotFound(true);
      return false;
    }
  }, [callId, toast]);

  const ended = outcome !== null;
  const endedRef = useRef(false);

  useEffect(() => {
    endedRef.current = ended;
    if (!ended) return;
    const s = session.current;
    session.current = null;
    setVoice('off');
    setPhone('off');
    void s?.disconnect().catch(() => undefined);
  }, [ended]);

  // the transcript can change from outside this page while voice connects or runs, a phone is dialled, rings or is
  // answered, or a typed turn is being answered; at any other time only another operator could change the call
  const liveLeg = voice !== 'off' || phone !== 'off' || sending;
  useCallPolling(refresh, { callId, live: liveLeg, ended });

  useEffect(() => {
    unmounted.current = false;
    return () => {
      unmounted.current = true;
      void session.current?.disconnect();
    };
  }, []);

  const lines = mergeTranscript(call?.transcript ?? [], live);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' });
  }, [lines.length]);

  useEffect(() => {
    if (!ended || !call) return;
    api.getCase(call.caseId).then(setKase).catch(() => setKase(null));
  }, [ended, call?.caseId]);

  useEffect(() => {
    void getPhoneAllowed().then((a) => {
      if (unmounted.current) return;
      setPhoneAllowed(a);
      setPhoneNumber(a.numbers[0]?.id ?? '');
    });
  }, []);

  const turnCount = call?.transcript.length ?? 0;
  useEffect(() => {
    if (phone === 'ringing' && turnCount > turnsAtDial.current) setPhone('live');
  }, [phone, turnCount]);

  useEffect(() => {
    if (phone !== 'ringing') return;
    const t = setTimeout(() => setPhone('off'), PHONE_RING_TIMEOUT_MS);
    return () => clearTimeout(t);
  }, [phone]);

  async function callPhone() {
    setPhone('dialling');
    turnsAtDial.current = turnCount;
    try {
      await placePhoneCall(callId, phoneNumber);
      if (!unmounted.current && !endedRef.current) setPhone('ringing');
    } catch (e) {
      if (unmounted.current) return;
      setPhone('off');
      toast.error(e);
    }
  }

  async function connect() {
    setVoice('connecting');
    try {
      const s = await connectVoice(callId, audio.current, {
        onUserText: (text) => setLive((l) => [...l, { role: CallTurnRole.USER, text }]),
        onBotText: (text) => setLive((l) => [...l, { role: CallTurnRole.AGENT, text }]),
        onDisconnected: () => setVoice('off'),
        onError: (m) => toast.push('Voice connection problem', m, 'warn'),
      });
      if (unmounted.current || endedRef.current) {
        void s.disconnect().catch(() => undefined);
        if (!unmounted.current) setVoice('off');
        return;
      }
      session.current = s;
      setVoice('on');
    } catch (e) {
      if (unmounted.current) return;
      setVoice('off');
      toast.push('Could not connect the voice call', e instanceof Error ? e.message : 'Check the voice service and microphone permission.', 'bad');
    }
  }

  async function finish() {
    setEnding(true);
    try {
      await session.current?.disconnect().catch(() => undefined);
      session.current = null;
      setVoice('off');
      const r = await endCall(callId);
      setOutcome(r.outcome);
      await refresh();
    } catch (e) {
      toast.error(e);
    } finally {
      setEnding(false);
    }
  }

  async function send(e: FormEvent) {
    e.preventDefault();
    const text = typed.trim();
    if (!text) return;
    setSending(true);
    try {
      if (!textStarted.current) {
        await textCall(callId);
        textStarted.current = true;
      }
      await textTurn(callId, text);
      setTyped('');
      await refresh();
    } catch (err) {
      toast.error(err);
    } finally {
      setSending(false);
    }
  }

  if (notFound && !call) {
    return (
      <div className="empty">
        <strong>This call could not be loaded</strong>
        <Link to={Route.RENEWALS}>Back to renewals</Link>
      </div>
    );
  }
  if (!call) return <p className="muted">Loading call…</p>;

  const guards = guardrails(call);
  const liveCall = !ended;
  const phoneBusy = phone === 'ringing' || phone === 'live';

  return (
    <>
      <div className="case-head">
        <Link to={Route.RENEWALS} className="small">
          ← Renewals
        </Link>
        <div className="page-head">
          <div style={{ display: 'grid', gap: 6 }}>
            <h1>{call.holderName}</h1>
            <div className="case-meta">
              {ended ? (
                <span className={`pill ${OUTCOME_TONE[outcome]}`}>
                  <span className="dot" aria-hidden="true" />
                  {OUTCOME_LABEL[outcome]}
                </span>
              ) : (
                <span className={`pill ${voice === 'on' ? 'info pulse' : 'dim'}`}>
                  <span className="dot" aria-hidden="true" />
                  {voice === 'on' ? 'Voice live' : voice === 'connecting' ? 'Connecting…' : 'Call open'}
                </span>
              )}
              <span className="mono small muted">{call.policyId}</span>
            </div>
          </div>
          {liveCall && (
            <div className="row">
              {voice === 'off' && (
                <button className={`btn${phone === 'off' ? ' primary' : ''}`} onClick={connect}>
                  Connect voice
                </button>
              )}
              {phoneBusy && (
                <>
                  <span className="pill info pulse">
                    <span className="dot" aria-hidden="true" />
                    {phone === 'live' ? 'Phone live' : 'Phone ringing'}
                  </span>
                  <button className="btn" onClick={() => setPhone('off')} title="Stops waiting here; it does not hang up the phone.">
                    Cancel
                  </button>
                </>
              )}
              {voice === 'off' && !phoneBusy && (
                <>
                  <Select
                    aria-label="Phone number"
                    value={phoneNumber}
                    onChange={setPhoneNumber}
                    disabled={!phoneAllowed.configured || phone !== 'off'}
                    options={phoneAllowed.numbers.map((n) => ({ value: n.id, label: n.masked }))}
                  />
                  <button
                    className="btn"
                    onClick={callPhone}
                    disabled={!phoneAllowed.configured || !phoneNumber || phone !== 'off'}
                    title={phoneAllowed.configured ? undefined : 'Phone calls are not set up on the voice service.'}
                  >
                    Call a phone
                  </button>
                  {!phoneAllowed.configured && <span className="small muted">Phone calls are not set up on the voice service.</span>}
                </>
              )}
              {voice === 'connecting' && (
                <button className="btn" disabled>
                  Connecting…
                </button>
              )}
              <button
                className="btn danger"
                onClick={finish}
                disabled={ending || phoneBusy}
                title={phoneBusy ? PHONE_END_HINT : undefined}
                aria-describedby={phoneBusy ? 'phone-end-hint' : undefined}
              >
                {voice === 'on' ? 'Hang up' : 'End call'}
              </button>
              {phoneBusy && (
                <span id="phone-end-hint" className="small muted">
                  {PHONE_END_HINT}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <audio ref={audio} autoPlay />

      <div className="call-grid">
        <section className="panel call-transcript" aria-label="Transcript">
          <div className="transcript" role="log" aria-live="polite">
            {lines.map((t, i) => (
              <div key={i} className={`turn ${t.role === CallTurnRole.AGENT ? 'agent' : 'user'}`}>
                <span className="who">{t.role === CallTurnRole.AGENT ? 'Agent' : 'Customer'}</span>
                <p>{t.text}</p>
              </div>
            ))}
            {lines.length === 0 && <span className="muted small">The transcript appears here.</span>}
            <div ref={endRef} />
          </div>
          {liveCall && (
            <form className="row type-row" onSubmit={send}>
              <div className="field" style={{ flex: 1 }}>
                <label htmlFor="type-instead">Type instead</label>
                <input
                  id="type-instead"
                  type="text"
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  disabled={voice !== 'off' || sending}
                  placeholder={voice === 'off' ? 'Say it in text, no microphone needed' : 'Hang up to type instead'}
                />
              </div>
              <button type="submit" className="btn" disabled={voice !== 'off' || sending || !typed.trim()}>
                Send
              </button>
            </form>
          )}
        </section>

        <aside style={{ display: 'grid', gap: 12, alignContent: 'start' }}>
          <section className="panel guard-panel" aria-label="Guardrails">
            <h2>Guardrails</h2>
            <ul>
              {guards.map((g) => (
                <li key={g.key}>
                  <span className={`gdot ${g.state}`} data-testid={`guard-${g.key}`} data-state={g.state} role="img" aria-label={`${g.label}: ${g.state}`} />
                  <div>
                    <strong>{g.label}</strong>
                    <div className="small muted">{g.note}</div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel guard-panel" aria-label="Call facts">
            <h2>Call facts</h2>
            <Facts call={call} />
          </section>
        </aside>
      </div>

      {ended && (
        <section style={{ display: 'grid', gap: 12, marginTop: 16 }} aria-label="After the call">
          <div className="panel guard-panel">
            <h2>Summary</h2>
            {call.summary.length === 0 && <span className="muted small">No summary points were recorded.</span>}
            <ul className="summary">
              {call.summary.map((s, i) => (
                <li key={i}>
                  <span>{s.statement}</span>
                  <blockquote>{s.quote}</blockquote>
                </li>
              ))}
            </ul>
          </div>
          <div className="panel guard-panel">
            <h2>Audit chain</h2>
            <AuditTab caseId={call.caseId} canVerify={can(Role.ADMIN)} />
          </div>
          <div className="panel guard-panel">
            <h2>Decision</h2>
            <p className="small muted">The person who started this call cannot decide it: sign in as the reviewer to approve.</p>
            {kase ? (
              <CaseActions kase={kase} canDecide={can(Role.REVIEWER)} onDone={() => api.getCase(call.caseId).then(setKase)} />
            ) : (
              <span className="muted small">Loading the case…</span>
            )}
          </div>
        </section>
      )}
    </>
  );
}
