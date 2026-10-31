import { useEffect, useState } from 'react';
import { BrowserRouter, NavLink, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { MOCK_MODE } from './api/client';
import { Select } from './components/Select';
import { ToastProvider } from './components/Toasts';
import { Call } from './pages/Call';
import { Dashboard } from './pages/Dashboard';
import { CaseWorkspace } from './pages/CaseWorkspace';
import { Packs } from './pages/Packs';
import { Queue } from './pages/Queue';
import { Renewals } from './pages/Renewals';
import { SignIn } from './pages/SignIn';
import { SupportCall } from './pages/SupportCall';
import { SupportDesk } from './pages/SupportDesk';
import { primaryRole, SessionProvider, useSession } from './session';
import { humanise } from './format';

const Theme = { LIGHT: 'light', DARK: 'dark' } as const;
type Theme = (typeof Theme)[keyof typeof Theme];
const THEME_KEY = 'ci-theme';
const THEME_OPTIONS = [
  { value: Theme.LIGHT, label: 'Light' },
  { value: Theme.DARK, label: 'Dark' },
];

function storedTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === Theme.DARK ? Theme.DARK : Theme.LIGHT;
  } catch {
    return Theme.LIGHT;
  }
}

function ThemeIcon({ theme }: { theme: Theme }) {
  return theme === Theme.DARK ? (
    <svg viewBox="0 0 16 16" width="14" height="14">
      <path d="M13.5 9.8A5.6 5.6 0 0 1 6.2 2.5a5.6 5.6 0 1 0 7.3 7.3z" fill="currentColor" />
    </svg>
  ) : (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <circle cx="8" cy="8" r="3" fill="currentColor" stroke="none" />
      <path d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3 3l1.1 1.1M11.9 11.9 13 13M3 13l1.1-1.1M11.9 4.1 13 3" />
    </svg>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);
  return (
    <Select
      aria-label="Theme"
      tone="dark"
      value={theme}
      options={THEME_OPTIONS}
      onChange={(v) => setTheme(v as Theme)}
      icon={<ThemeIcon theme={theme} />}
    />
  );
}

function Shell() {
  const { session, signOut } = useSession();
  if (!session) return <SignIn />;
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">AC</span>
          <span>Azentio-CSM</span>
          {MOCK_MODE && <span className="pill warn">Mock data</span>}
        </div>
        <nav className="nav" aria-label="Main">
          <NavLink to="/support">Support desk</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/queue">Queue</NavLink>
          <NavLink to="/renewals">Renewals</NavLink>
          <NavLink to="/packs">Rule packs</NavLink>
        </nav>
        <div className="topbar-right">
          <ThemeToggle />
          <span className="small">
            <strong>{session.username}</strong> <span className="pill neutral">{humanise(primaryRole(session.roles))}</span>
          </span>
          <button className="btn ghost sm" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

export function App() {
  return (
    <ToastProvider>
      <SessionProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Shell />}>
              <Route index element={<Navigate to="/support" replace />} />
              <Route path="support" element={<SupportDesk />} />
              <Route path="support/new" element={<SupportCall />} />
              <Route path="support/calls/:callId" element={<SupportCall />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="queue" element={<Queue />} />
              <Route path="cases/:id" element={<CaseWorkspace />} />
              <Route path="renewals" element={<Renewals />} />
              <Route path="renewals/calls/:callId" element={<Call />} />
              <Route path="packs" element={<Packs />} />
              <Route path="*" element={<Navigate to="/support" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </SessionProvider>
    </ToastProvider>
  );
}
