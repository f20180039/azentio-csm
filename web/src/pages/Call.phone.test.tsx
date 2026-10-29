import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect, type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  allowed: { configured: false, numbers: [] as { id: string; masked: string }[] },
  placed: [] as [string, string][],
}));

vi.mock('../api/phone', () => ({
  getPhoneAllowed: vi.fn(async () => h.allowed),
  placePhoneCall: vi.fn(async (callId: string, numberId: string) => {
    h.placed.push([callId, numberId]);
    return { twilioCallSid: 'CA1' };
  }),
}));

async function mount(callId = 'sample-call-phone') {
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
          <MemoryRouter initialEntries={[`/renewals/calls/${callId}`]}>
            <Routes>
              <Route path="/renewals/calls/:callId" element={<Call />} />
            </Routes>
          </MemoryRouter>
        </SignedIn>
      </SessionProvider>
    </ToastProvider>,
  );
}

describe('Call page: call a phone', () => {
  it('is disabled with a reason when phone calls are not set up', async () => {
    h.allowed = { configured: false, numbers: [] };
    await mount();
    const button = await screen.findByRole('button', { name: 'Call a phone' });
    expect(button).toBeDisabled();
    expect(screen.getByText(/phone calls are not set up/i)).toBeInTheDocument();
  });

  it('dials the chosen masked number', async () => {
    h.allowed = {
      configured: true,
      numbers: [
        { id: '0', masked: '+91 ••••• •4417' },
        { id: '1', masked: '+1 ••••• •0123' },
      ],
    };
    h.placed = [];
    await mount('sample-call-phone-2');
    const select = (await screen.findByLabelText('Phone number')) as HTMLSelectElement;
    expect(screen.getByRole('option', { name: '+91 ••••• •4417' })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: '1' } });
    const button = screen.getByRole('button', { name: 'Call a phone' });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(h.placed).toEqual([['sample-call-phone-2', '1']]));
    expect(await screen.findByText('Phone ringing')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Connect' })).not.toBeInTheDocument();
  });
});
