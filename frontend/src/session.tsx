import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { api, setCredentials, type Credentials, type Session } from './api/client';
import { Role, StorageKey } from './vocab';

interface SessionCtx {
  session: Session | null;
  signIn: (c: Credentials) => Promise<void>;
  signOut: () => void;
  can: (role: Role) => boolean;
}

const Ctx = createContext<SessionCtx | null>(null);

function loadStoredSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(StorageKey.SESSION);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Session;
    if (parsed?.username && parsed?.password && Array.isArray(parsed?.roles)) {
      setCredentials(parsed);
      return parsed;
    }
  } catch {
    /* storage corrupted or unavailable */
  }
  return null;
}

/** Session is persisted in sessionStorage so page refreshes maintain the logged-in state. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadStoredSession);

  const signIn = useCallback(async (c: Credentials) => {
    const s = await api.signIn(c);
    setSession(s);
    try {
      sessionStorage.setItem(StorageKey.SESSION, JSON.stringify(s));
    } catch {
      /* storage unavailable */
    }
  }, []);

  const signOut = useCallback(() => {
    try {
      sessionStorage.removeItem(StorageKey.SESSION);
    } catch {
      /* storage unavailable */
    }
    setCredentials(null);
    setSession(null);
  }, []);

  const value = useMemo<SessionCtx>(
    () => ({ session, signIn, signOut, can: (role) => !!session?.roles.includes(role) }),
    [session, signIn, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useSession outside SessionProvider');
  return v;
}

export function primaryRole(roles: Role[]): Role {
  if (roles.includes(Role.ADMIN)) return Role.ADMIN;
  if (roles.includes(Role.REVIEWER)) return Role.REVIEWER;
  return Role.ANALYST;
}
