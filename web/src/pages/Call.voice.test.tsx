import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect, type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  failTurn: false,
  resolveConnect: null as null | ((s: { disconnect: () => Promise<void> }) => void),
}));

vi.mock('../api/voice', () => ({
  connectVoice: vi.fn(() => new Promise((resolve) => (h.resolveConnect = resolve))),
}));
vi.mock('../api/renewals', async (orig) => {
  const real = await orig<typeof import('../api/renewals')>();
  return {
    ...real,
    textTurn: (id: string, text: string) =>
      h.failTurn ? Promise.reject(new Error('voice service down')) : real.textTurn(id, text),
  };
});

async function mount() {
  vi.stubEnv('VITE_MOCK', '1');
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  const { MemoryRouter, Route, Routes } = await import('react-router-dom');
  const { ToastProvider } = await import('../components/Toasts');
  const { SessionProvider, useSession } = await import('../session');
  const { Call } = await import('./Call');
  await (await import('../api/client')).api.signIn({ username: 'reviewer', password: 'reviewer' });
  function SignedIn({ children }: { children: ReactNode }) {
    const { signIn, session } = useSession();
    useEffect(() => {
      void signIn({ username: 'reviewer', password: 'reviewer' });
    }, [signIn]);
    return session ? <>{children}</> : null;
  }
  return render(
    <ToastProvider>
      <SessionProvider>
        <SignedIn>
          <MemoryRouter initialEntries={['/renewals/calls/sample-call-x']}>
            <Routes>
              <Route path="/renewals/calls/:callId" element={<Call />} />
            </Routes>
          </MemoryRouter>
        </SignedIn>
      </SessionProvider>
    </ToastProvider>,
  );
}

describe('Call page voice and typing edge cases', () => {
  it('disconnects a session that finishes connecting after unmount', async () => {
    const view = await mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Connect' }));
    await waitFor(() => expect(h.resolveConnect).not.toBeNull());
    view.unmount();
    const disconnect = vi.fn(() => Promise.resolve());
    h.resolveConnect!({ disconnect });
    await waitFor(() => expect(disconnect).toHaveBeenCalledTimes(1));
  });

  it('keeps the typed message when sending fails', async () => {
    h.failTurn = true;
    await mount();
    const input = (await screen.findByLabelText('Type instead')) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'my date of birth is 1984' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByText('voice service down')).toBeInTheDocument();
    expect(input.value).toBe('my date of birth is 1984');
  });
});
