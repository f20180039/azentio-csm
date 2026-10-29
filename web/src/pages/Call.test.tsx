import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect, useState, type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

describe('Call page in mock mode', () => {
  it('runs a scripted call: identity turns ok and the outcome reads payment pending', async () => {
    vi.stubEnv('VITE_MOCK', '1');
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    const { MemoryRouter, Route, Routes } = await import('react-router-dom');
    const { ToastProvider } = await import('../components/Toasts');
    const { SessionProvider, useSession } = await import('../session');
    const { Call } = await import('./Call');
    const { startCall } = await import('../api/renewals');

    function SignedIn({ children }: { children: ReactNode }) {
      const { signIn, session } = useSession();
      useEffect(() => {
        void signIn({ username: 'reviewer', password: 'reviewer' });
      }, [signIn]);
      return session ? <>{children}</> : null;
    }
    function Harness() {
      const [callId, setCallId] = useState<string | null>(null);
      useEffect(() => {
        void startCall('LL-MOT-20418').then((c) => setCallId(c.callId));
      }, []);
      if (!callId) return null;
      return (
        <MemoryRouter initialEntries={[`/renewals/calls/${callId}`]}>
          <Routes>
            <Route path="/renewals/calls/:callId" element={<Call />} />
          </Routes>
        </MemoryRouter>
      );
    }
    await (await import('../api/client')).api.signIn({ username: 'reviewer', password: 'reviewer' });
    render(
      <ToastProvider>
        <SessionProvider>
          <SignedIn>
            <Harness />
          </SignedIn>
        </SessionProvider>
      </ToastProvider>,
    );

    const identity = await screen.findByTestId('guard-identity');
    expect(identity).toHaveAttribute('data-state', 'idle');

    const input = await screen.findByLabelText('Type instead');
    const send = (text: string) => {
      fireEvent.change(input, { target: { value: text } });
      fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    };
    send('Yes, go ahead');
    await screen.findByText(/date of birth/i);
    send('12 March 1984');
    await waitFor(() => expect(screen.getByTestId('guard-identity')).toHaveAttribute('data-state', 'ok'));
    send('Drop roadside assistance and pay quarterly');
    await waitFor(() => expect(screen.getByTestId('guard-links')).toHaveTextContent(/sent/i));

    fireEvent.click(screen.getByRole('button', { name: 'End call' }));
    expect(await screen.findByText('Renewed with changes · payment pending')).toBeInTheDocument();
  });

  it('maps call state to guardrail colours', async () => {
    const { guardrails } = await import('./Call');
    const base: import('../api/types').CallView = {
      callId: 'c', caseId: 'c', policyId: 'p', holderName: 'h', greeting: 'g', identityVerified: false, verifyFailures: 0,
      outOfPlaybookRequests: 0, mustHandoff: false, outcome: null, lastQuote: null, paymentLinkSent: false,
      handoffReason: null, callbackAt: null, transcript: [{ role: 'agent', text: 'hi' }], summary: [],
    };
    const state = (c: import('../api/types').CallView, key: string) => guardrails(c).find((g) => g.key === key)!.state;
    expect(state(base, 'disclosure')).toBe('ok');
    expect(state({ ...base, verifyFailures: 1 }, 'identity')).toBe('warn');
    expect(state({ ...base, verifyFailures: 3, mustHandoff: true }, 'identity')).toBe('bad');
    expect(state({ ...base, outOfPlaybookRequests: 1 }, 'playbook')).toBe('warn');
    expect(state({ ...base, mustHandoff: true, handoffReason: 'x' }, 'handoff')).toBe('bad');
  });
});
