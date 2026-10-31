import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect, type ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  allowed: { configured: false, numbers: [] as { id: string; masked: string }[] },
  placed: [] as [string, string][],
}));

vi.mock('../api/phone', async (orig) => ({
  ...(await orig<typeof import('../api/phone')>()),
  getPhoneAllowed: vi.fn(async () => h.allowed),
  placePhoneCall: vi.fn(async (callId: string, numberId: string) => {
    h.placed.push([callId, numberId]);
    return { status: 'dialling' };
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
    const select = await screen.findByLabelText('Phone number');
    await waitFor(() => expect(select).toBeEnabled());
    fireEvent.click(select);
    expect(screen.getByRole('option', { name: '+91 ••••• •4417' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('option', { name: '+1 ••••• •0123' }));
    const button = screen.getByRole('button', { name: 'Call a phone' });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await waitFor(() => expect(h.placed).toEqual([['sample-call-phone-2', '1']]));
    expect(await screen.findByText('Phone ringing')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect voice' })).toBeEnabled();
  });

  it('while the phone rings, End call is disabled with a hint and Cancel returns to the dial controls', async () => {
    h.allowed = { configured: true, numbers: [{ id: '0', masked: '+91 ••••• •4417' }] };
    await mount('sample-call-phone-3');
    const dial = await screen.findByRole('button', { name: 'Call a phone' });
    await waitFor(() => expect(dial).toBeEnabled());
    fireEvent.click(dial);
    expect(await screen.findByText('Phone ringing')).toBeInTheDocument();
    const end = screen.getByRole('button', { name: 'End call' });
    expect(end).toBeDisabled();
    expect(end).toHaveAttribute('title', 'Hang up on the phone (or let the agent end the call)');
    expect(screen.getByText('Hang up on the phone (or let the agent end the call)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect voice' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByText('Phone ringing')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'End call' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Call a phone' })).toBeEnabled();
  });

  it('stops showing a ringing phone after two minutes', async () => {
    h.allowed = { configured: true, numbers: [{ id: '0', masked: '+91 ••••• •4417' }] };
    await mount('sample-call-phone-4');
    const dial = await screen.findByRole('button', { name: 'Call a phone' });
    await waitFor(() => expect(dial).toBeEnabled());
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    await act(async () => {
      fireEvent.click(dial);
    });
    expect(screen.getByText('Phone ringing')).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(119_000);
    });
    expect(screen.getByText('Phone ringing')).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(screen.queryByText('Phone ringing')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'End call' })).toBeEnabled();
  });
});

afterEach(() => vi.useRealTimers());
