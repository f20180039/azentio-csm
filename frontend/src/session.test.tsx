import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { SessionProvider, useSession } from './session';
import { StorageKey, Role } from './vocab';
import type { ReactNode } from 'react';

const wrapper = ({ children }: { children: ReactNode }) => (
  <SessionProvider>{children}</SessionProvider>
);

describe('SessionProvider persistence', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('initializes with null session when storage is empty', () => {
    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.session).toBeNull();
  });

  it('restores existing session from sessionStorage upon initialization', () => {
    const stored = { username: 'analyst', password: 'password', roles: [Role.ANALYST] };
    sessionStorage.setItem(StorageKey.SESSION, JSON.stringify(stored));

    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.session).toEqual(stored);
    expect(result.current.can(Role.ANALYST)).toBe(true);
    expect(result.current.can(Role.ADMIN)).toBe(false);
  });

  it('clears sessionStorage when signing out', () => {
    const stored = { username: 'reviewer', password: 'password', roles: [Role.REVIEWER] };
    sessionStorage.setItem(StorageKey.SESSION, JSON.stringify(stored));

    const { result } = renderHook(() => useSession(), { wrapper });
    expect(result.current.session).not.toBeNull();

    act(() => {
      result.current.signOut();
    });

    expect(result.current.session).toBeNull();
    expect(sessionStorage.getItem(StorageKey.SESSION)).toBeNull();
  });
});
