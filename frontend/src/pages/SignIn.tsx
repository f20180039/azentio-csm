import { useState, type FormEvent } from 'react';
import { ApiError } from '../api/errors';
import { MOCK_MODE } from '../api/client';
import { SignInArt } from '../components/SignInArt';
import { DEMO_USERS } from '../demoUsers';
import { useSession } from '../session';

export function SignIn() {
  const { signIn } = useSession();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    await attempt(username.trim(), password);
  }

  async function attempt(user: string, pass: string) {
    setBusy(true);
    setError(null);
    try {
      await signIn({ username: user, password: pass });
    } catch (err) {
      setError(err instanceof ApiError ? (err.detail ? `${err.title}. ${err.detail}` : err.title) : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin-wrap">
      <div className="signin-shell">
      <aside className="signin-art">
        <div className="signin-art-brand">
          <span className="brand-mark" aria-hidden="true">AC</span>
          <span>Azentio-CSM</span>
        </div>
        <SignInArt />
        <div className="signin-art-copy">
          <h2>The bank&rsquo;s customer service line, answered by a voice agent</h2>
          <ul>
            <li>Understands what the caller needs, even with accents and noise</li>
            <li>Verifies identity before sharing anything personal</li>
            <li>Answers from the bank&rsquo;s systems and raises tickets</li>
          </ul>
        </div>
      </aside>
      <div className="signin">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">AC</span>
          <span>Azentio-CSM</span>
        </div>
        <div className="signin-intro">
          <h1>Sign in</h1>
          <p className="muted small">Sign in with your username and password, or pick a team member below. Your role decides what you can change; reloading signs you out.</p>
        </div>
        {MOCK_MODE && (
          <p className="mock-note">
            <span className="dot" aria-hidden="true" />
            Mock mode: example data only, nothing reaches a server.
          </p>
        )}
        {error && (
          <div className="banner bad" role="alert">
            {error}
          </div>
        )}
        <form className="signin-form" onSubmit={submit}>
          <div className="field">
            <label htmlFor="signin-user">Username</label>
            <input id="signin-user" type="text" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="signin-pass">Password</label>
            <input id="signin-pass" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          <p className="small muted">Demo accounts use the username as the password.</p>
        </form>
        <div className="signin-divider" role="separator">
          <span>or sign in as a team member</span>
        </div>
        <ul className="personas" aria-label="Demo personas">
          {DEMO_USERS.map((u) => (
            <li key={u.username}>
              <button
                type="button"
                className="persona"
                disabled={busy}
                aria-label={`Sign in as ${u.name}, ${u.role}`}
                aria-describedby={`persona-${u.username}-can`}
                onClick={() => {
                  setUsername(u.username);
                  setPassword(u.username);
                  attempt(u.username, u.username);
                }}
              >
                <span className={`persona-avatar ${u.username}`} aria-hidden="true">
                  {u.initials}
                </span>
                <span className="persona-body">
                  <strong>
                    {u.name} <span className="pill neutral persona-role">{u.role}</span>
                  </strong>
                  <span className="small muted" id={`persona-${u.username}-can`}>
                    {u.can}
                  </span>
                </span>
                <span className="persona-go" aria-hidden="true">
                  Sign in as {u.name}
                  <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M6 3l5 5-5 5" />
                  </svg>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      </div>
    </div>
  );
}
