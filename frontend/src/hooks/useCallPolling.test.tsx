import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  CALL_POLL_FAST_MS,
  CALL_POLL_SETTLE_MS,
  CALL_POLL_SLOW_MS,
  CALL_RECENT_ACTIVITY_MS,
  recentActivity,
  useCallPolling,
  type CallPollingOptions,
} from './useCallPolling';

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (hidden ? 'hidden' : 'visible') });
  document.dispatchEvent(new Event('visibilitychange'));
}

const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
const open = (o: Partial<CallPollingOptions> = {}): CallPollingOptions => ({ callId: 'call-1', live: false, ended: false, ...o });

function mount(initial: Partial<CallPollingOptions> = {}, refresh = vi.fn(async () => true)) {
  const view = renderHook((o: CallPollingOptions) => useCallPolling(refresh, o), { initialProps: open(initial) });
  return { refresh, ...view };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  setHidden(false);
  vi.useRealTimers();
});

describe('useCallPolling', () => {
  it('loads once at mount', async () => {
    const { refresh } = mount();
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('loads once when mounted, unmounted and mounted again at once (StrictMode rehearsal)', async () => {
    const refresh = vi.fn(async () => true);
    const first = renderHook((o: CallPollingOptions) => useCallPolling(refresh, o), { initialProps: open() });
    first.unmount();
    renderHook((o: CallPollingOptions) => useCallPolling(refresh, o), { initialProps: open() });
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('polls an idle open call about once every 10 s, not every second', async () => {
    expect(CALL_POLL_SLOW_MS).toBe(10_000);
    const { refresh } = mount();
    await tick(0);
    await tick(CALL_POLL_SLOW_MS - 1);
    expect(refresh).toHaveBeenCalledTimes(1);
    await tick(1);
    expect(refresh).toHaveBeenCalledTimes(2);
    await tick(CALL_POLL_SLOW_MS * 3);
    expect(refresh).toHaveBeenCalledTimes(5);
  });

  it('polls once a second while something live can change the call', async () => {
    expect(CALL_POLL_FAST_MS).toBe(1000);
    const { refresh } = mount({ live: true });
    await tick(0);
    await tick(CALL_POLL_FAST_MS * 5);
    expect(refresh).toHaveBeenCalledTimes(6);
  });

  it('switches to the fast interval as soon as the call goes live, without waiting out the slow timer', async () => {
    const { refresh, rerender } = mount();
    await tick(0);
    await tick(5000);
    expect(refresh).toHaveBeenCalledTimes(1);
    rerender(open({ live: true }));
    await tick(CALL_POLL_FAST_MS);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it('keeps the fast interval for the settle window after the live leg ends, then slows down', async () => {
    expect(CALL_POLL_SETTLE_MS).toBe(6000);
    const { refresh, rerender } = mount({ live: true });
    await tick(0);
    await tick(CALL_POLL_FAST_MS * 2);
    expect(refresh).toHaveBeenCalledTimes(3);
    rerender(open({ live: false }));
    await tick(CALL_POLL_SETTLE_MS);
    expect(refresh).toHaveBeenCalledTimes(3 + CALL_POLL_SETTLE_MS / CALL_POLL_FAST_MS); // the closing turn and hang-up land promptly
    const settled = refresh.mock.calls.length;
    await tick(CALL_POLL_FAST_MS * 3);
    expect(refresh).toHaveBeenCalledTimes(settled);
    await tick(CALL_POLL_SLOW_MS);
    expect(refresh).toHaveBeenCalledTimes(settled + 1);
  });

  it('does not open a settle window when the call was never live', async () => {
    const { refresh, rerender } = mount();
    await tick(0);
    rerender(open({ live: false, lastTurnAt: null }));
    await tick(CALL_POLL_SETTLE_MS);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  describe('recent activity in the record', () => {
    it('names the window and reads an ISO timestamp', () => {
      expect(CALL_RECENT_ACTIVITY_MS).toBe(15_000);
      expect(recentActivity(ago(5000))).toBe(true);
      expect(recentActivity(ago(CALL_RECENT_ACTIVITY_MS))).toBe(false);
      expect(recentActivity(ago(10 * 60_000))).toBe(false);
      expect(recentActivity(null)).toBe(false);
      expect(recentActivity(undefined)).toBe(false);
      expect(recentActivity('not a date')).toBe(false);
    });

    it('polls fast while the latest turn is recent, even though nothing on this page is live', async () => {
      const { refresh } = mount({ lastTurnAt: ago(5000) });
      await tick(0);
      await tick(CALL_POLL_FAST_MS * 5);
      expect(refresh).toHaveBeenCalledTimes(6);
    });

    it('polls slowly when the latest turn is old', async () => {
      const { refresh } = mount({ lastTurnAt: ago(10 * 60_000) });
      await tick(0);
      await tick(CALL_POLL_FAST_MS * 5);
      expect(refresh).toHaveBeenCalledTimes(1);
    });

    it('slows down once the latest turn has aged past the window', async () => {
      const { refresh } = mount({ lastTurnAt: ago(0) });
      await tick(0);
      await tick(CALL_RECENT_ACTIVITY_MS);
      const atWindow = refresh.mock.calls.length;
      expect(atWindow).toBeGreaterThanOrEqual(CALL_RECENT_ACTIVITY_MS / CALL_POLL_FAST_MS);
      await tick(CALL_POLL_FAST_MS * 5);
      expect(refresh).toHaveBeenCalledTimes(atWindow);
    });

    it('speeds up as soon as a new turn arrives', async () => {
      const { refresh, rerender } = mount({ lastTurnAt: ago(10 * 60_000) });
      await tick(0);
      await tick(5000);
      expect(refresh).toHaveBeenCalledTimes(1);
      rerender(open({ lastTurnAt: ago(0) }));
      await tick(CALL_POLL_FAST_MS);
      expect(refresh).toHaveBeenCalledTimes(2);
    });
  });

  it('makes no requests while the tab is hidden and refreshes at once when it is visible again', async () => {
    const { refresh } = mount({ live: true });
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
    act(() => setHidden(true));
    await tick(CALL_POLL_SLOW_MS * 3);
    expect(refresh).toHaveBeenCalledTimes(1);
    act(() => setHidden(false));
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(2);
    await tick(CALL_POLL_FAST_MS * 2);
    expect(refresh).toHaveBeenCalledTimes(4);
  });

  it('does not even load while hidden; the first load waits for the tab', async () => {
    setHidden(true);
    const { refresh } = mount();
    await tick(CALL_POLL_SLOW_MS);
    expect(refresh).not.toHaveBeenCalled();
    act(() => setHidden(false));
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('does not refresh on a tab switch when no poll was skipped', async () => {
    const { refresh } = mount();
    await tick(0);
    act(() => setHidden(true));
    await tick(1000); // back before the next slow poll was due
    act(() => setHidden(false));
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('drops to the slow interval after a failed poll until one succeeds', async () => {
    const refresh = vi.fn(async () => false);
    mount({ live: true }, refresh);
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1); // failed
    await tick(CALL_POLL_FAST_MS * 5);
    expect(refresh).toHaveBeenCalledTimes(1);
    await tick(CALL_POLL_SLOW_MS - CALL_POLL_FAST_MS * 5);
    expect(refresh).toHaveBeenCalledTimes(2); // failed again
    refresh.mockResolvedValue(true);
    await tick(CALL_POLL_SLOW_MS);
    expect(refresh).toHaveBeenCalledTimes(3); // succeeded: fast again
    await tick(CALL_POLL_FAST_MS);
    expect(refresh).toHaveBeenCalledTimes(4);
  });

  it('treats a refresh that throws as a failed poll', async () => {
    const refresh = vi.fn<() => Promise<boolean>>(async () => {
      throw new Error('boom');
    });
    mount({ live: true }, refresh);
    await tick(0);
    await tick(CALL_POLL_FAST_MS * 3);
    expect(refresh).toHaveBeenCalledTimes(1);
    await tick(CALL_POLL_SLOW_MS);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it('loads an ended call once and never polls it', async () => {
    const { refresh } = mount({ ended: true, live: true, lastTurnAt: ago(0) });
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
    await tick(CALL_POLL_SLOW_MS * 6);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('stops polling when the call ends, without fetching the record again', async () => {
    const { refresh, rerender } = mount({ live: true });
    await tick(0);
    await tick(CALL_POLL_FAST_MS * 2);
    expect(refresh).toHaveBeenCalledTimes(3);
    rerender(open({ live: false, ended: true })); // the poll that returned the ended record was the last load
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(3);
    await tick(CALL_POLL_SLOW_MS * 3);
    expect(refresh).toHaveBeenCalledTimes(3);
  });

  it('does not re-fetch an ended call on every tab switch', async () => {
    const { refresh } = mount({ ended: true });
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
    act(() => setHidden(true));
    await tick(CALL_POLL_SLOW_MS * 2);
    act(() => setHidden(false));
    await tick(CALL_POLL_SLOW_MS);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('does nothing without a call id and reloads when the id changes', async () => {
    const { refresh, rerender } = mount({ callId: null });
    await tick(CALL_POLL_SLOW_MS * 2);
    expect(refresh).not.toHaveBeenCalled();
    rerender(open({ callId: 'call-2' }));
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
    rerender(open({ callId: 'call-3' }));
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it('never runs two refreshes at once and stops on unmount', async () => {
    let inFlight = 0;
    let peak = 0;
    const refresh = vi.fn(async () => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((r) => setTimeout(r, CALL_POLL_FAST_MS * 3));
      inFlight -= 1;
      return true;
    });
    const { unmount } = mount({ live: true }, refresh);
    await tick(0);
    act(() => setHidden(false)); // a visibility event during a slow request must not start another
    await tick(CALL_POLL_FAST_MS * 10);
    expect(peak).toBe(1);
    const n = refresh.mock.calls.length;
    unmount();
    await tick(CALL_POLL_SLOW_MS * 2);
    expect(refresh).toHaveBeenCalledTimes(n);
  });

  it('uses the latest refresh function without restarting the schedule', async () => {
    const first = vi.fn(async () => true);
    const second = vi.fn(async () => true);
    const { rerender } = renderHook(({ fn }: { fn: () => Promise<boolean> }) => useCallPolling(fn, open({ live: true })), {
      initialProps: { fn: first },
    });
    await tick(0);
    expect(first).toHaveBeenCalledTimes(1);
    rerender({ fn: second });
    await tick(0);
    expect(second).not.toHaveBeenCalled(); // no extra request just because a callback identity changed
    await tick(CALL_POLL_FAST_MS);
    expect(second).toHaveBeenCalledTimes(1);
    expect(first).toHaveBeenCalledTimes(1);
  });
});
