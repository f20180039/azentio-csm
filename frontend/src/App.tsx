import { useEffect, useState } from 'react';
import { BrowserRouter, NavLink, Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { MOCK_MODE } from './api/client';
import { ToastProvider } from './components/Toasts';
import { Call } from './pages/Call';
import { Dashboard } from './pages/Dashboard';
import { CaseWorkspace } from './pages/CaseWorkspace';
import { Packs } from './pages/Packs';
import { Queue } from './pages/Queue';
import { Renewals } from './pages/Renewals';
import { SignIn } from './pages/SignIn';
import { BFSIAgentDesk } from './pages/BFSIAgentDesk';
import { SupportCall } from './pages/SupportCall';
import { SupportDesk } from './pages/SupportDesk';
import { primaryRole, SessionProvider, useSession } from './session';
import { humanise } from './format';

type Theme = 'system' | 'light' | 'dark';

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem('ci-theme') as Theme) || 'system';
    } catch {
      return 'system';
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
    try {
      localStorage.setItem('ci-theme', theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);
  return (
    <select aria-label="Theme" value={theme} onChange={(e) => setTheme(e.target.value as Theme)}>
      <option value="system">System theme</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
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
          <NavLink to="/agent-desk">Azentio-CSM Desk</NavLink>
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
              <Route path="/agent-desk" element={<BFSIAgentDesk />} />
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
