import { useState, type FormEvent } from 'react';
import { ApiError } from '../api/errors';
import { MOCK_MODE } from '../api/client';
import { useSession } from '../session';

const DEMO_USERS = [
  { username: 'analyst', role: 'Analyst', can: 'View cases and upload documents' },
  { username: 'reviewer', role: 'Reviewer', can: 'Also decide findings and cases' },
  { username: 'admin', role: 'Admin', can: 'Also verify the audit chain' },
];

export function SignIn() {
  const { signIn } = useSession();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn({ username: username.trim(), password });
    } catch (err) {
      setError(err instanceof ApiError ? (err.detail ? `${err.title}. ${err.detail}` : err.title) : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin-wrap">
      <form className="signin" onSubmit={submit}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">AC</span>
          <span>Azentio-CSM</span>
        </div>
        <div>
          <h1>Sign in</h1>
          <p className="muted small">Your role decides what you can change. Credentials stay in memory only, so reloading signs you out.</p>
        </div>
        {MOCK_MODE && <div className="banner info">Mock mode: all cases are example data and nothing reaches a server.</div>}
        <div className="field">
          <label htmlFor="signin-user">Username</label>
          <input id="signin-user" type="text" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="signin-pass">Password</label>
          <input id="signin-pass" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && (
          <div className="banner bad" role="alert">
            {error}
          </div>
        )}
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <div className="demo-users">
          <span className="label">Demo accounts (password = username)</span>
          {DEMO_USERS.map((u) => (
            <button
              key={u.username}
              type="button"
              className="btn ghost"
              onClick={() => {
                setUsername(u.username);
                setPassword(u.username);
              }}
            >
              <strong>{u.role}</strong> · <span className="mono">{u.username}</span> · {u.can}
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}
