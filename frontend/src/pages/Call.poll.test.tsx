import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CALL_POLL_FAST_MS, CALL_POLL_SLOW_MS, CALL_RECENT_ACTIVITY_MS } from '../hooks/useCallPolling';

const h = vi.hoisted(() => ({
  getCall: vi.fn(),
  connectVoice: vi.fn(),
  textTurn: vi.fn(),
  allowed: { configured: false, numbers: [] as { id: string; masked: string }[] },
  toast: null as null | { push: (title: string, detail?: string) => void },
}));

vi.mock('../api/renewals', async (orig) => {
  const real = await orig<typeof import('../api/renewals')>();
  h.getCall.mockImplementation(real.getCall);
  h.textTurn.mockImplementation(real.textTurn);
  return { ...real, getCall: h.getCall, textTurn: h.textTurn };
});
vi.mock('../api/voice', () => ({ connectVoice: h.connectVoice }));
vi.mock('../api/phone', async (orig) => ({
  ...(await orig<typeof import('../api/phone')>()),
  getPhoneAllowed: vi.fn(async () => h.allowed),
  placePhoneCall: vi.fn(async () => ({ status: 'dialling' })),
}));

async function mount(callId: string) {
  vi.stubEnv('VITE_MOCK', '1');
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  const { MemoryRouter, Route, Routes } = await import('react-router-dom');
  const { ToastProvider, useToast } = await import('../components/Toasts');
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
  /** Lets a test raise a toast from outside the page, the way another component on the screen would. */
  function Tap() {
    h.toast = useToast();
    return null;
  }
  render(
    <ToastProvider>
      <Tap />
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
  await screen.findByRole('button', { name: 'End call' });
  await act(() => vi.advanceTimersByTimeAsync(200)); // let the first load settle
}

const calls = () => h.getCall.mock.calls.length;
const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
/** A mock call opens with a greeting turn written "now", so it counts as recent activity; this outlives that window and any settle window. */
const waitQuiet = () => tick(CALL_RECENT_ACTIVITY_MS + CALL_POLL_FAST_MS * 2); // plus the last poll scheduled while still recent

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  h.allowed = { configured: false, numbers: [] };
  h.getCall.mockClear();
});
afterEach(() => vi.useRealTimers());

describe('Call page polling', () => {
  it('polls a just-started call fast (its greeting is recent activity), then about once every 10 s once nothing has happened for 15 s', async () => {
    await mount('sample-call-poll-1');
    let before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 3);
    await waitQuiet();
    before = calls();
    await tick(CALL_POLL_SLOW_MS + 500); // one slow period, whatever its phase: exactly one poll, not ten
    expect(calls()).toBe(before + 1);
  });

  it('polls every second while voice is connecting or on, and slows down again after hanging up', async () => {
    let connected: ((s: { disconnect: () => Promise<void> }) => void) | null = null;
    h.connectVoice.mockImplementation(() => new Promise((resolve) => (connected = resolve)));
    await mount('sample-call-poll-2');
    fireEvent.click(screen.getByRole('button', { name: 'Connect voice' }));
    await screen.findAllByText('Connecting…');
    let before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 3);

    await act(async () => connected!({ disconnect: vi.fn().mockResolvedValue(undefined) }));
    await screen.findByText('Voice live');
    before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 3);

    fireEvent.click(screen.getByRole('button', { name: 'Hang up' }));
    await waitFor(() => expect(screen.queryByText('Voice live')).not.toBeInTheDocument());
    await waitQuiet();
    before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeLessThanOrEqual(before + 1);
  });

  it('polls every second while a phone call is ringing, then slowly once the operator cancels', async () => {
    h.allowed = { configured: true, numbers: [{ id: '0', masked: '+91 ••••• •4417' }] };
    await mount('sample-call-poll-3');
    const dial = await screen.findByRole('button', { name: 'Call a phone' });
    await waitFor(() => expect(dial).toBeEnabled());
    fireEvent.click(dial);
    await screen.findByText('Phone ringing');
    let before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 3);

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitQuiet();
    before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeLessThanOrEqual(before + 1);
  });

  it('polls every second while a typed turn is in flight', async () => {
    let release: (() => void) | null = null;
    h.textTurn.mockImplementation(() => new Promise<void>((resolve) => (release = resolve)));
    await mount('sample-call-poll-4');
    fireEvent.change(screen.getByLabelText('Type instead'), { target: { value: 'Yes, go ahead' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(h.textTurn).toHaveBeenCalled());
    const before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 3);
    await act(async () => release!());
  });

  it('a toast does not restart polling (the memoised toast value itself is proven in Toasts.test.tsx)', async () => {
    await mount('sample-call-poll-5');
    await waitQuiet();
    const before = calls();
    await act(async () => h.toast!.push('Voice connection problem', 'ICE failed'));
    await screen.findByText('Voice connection problem');
    await tick(CALL_POLL_FAST_MS * 2);
    expect(calls()).toBe(before);
  });
});
