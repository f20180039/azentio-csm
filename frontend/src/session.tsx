import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { api, setCredentials, type Credentials, type Session } from './api/client';
import { Role } from './vocab';

interface SessionCtx {
  session: Session | null;
  signIn: (c: Credentials) => Promise<void>;
  signOut: () => void;
  can: (role: Role) => boolean;
}

const Ctx = createContext<SessionCtx | null>(null);

/** Credentials live only in memory: a reload signs the user out. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);

  const signIn = useCallback(async (c: Credentials) => {
    setSession(await api.signIn(c));
  }, []);

  const signOut = useCallback(() => {
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
