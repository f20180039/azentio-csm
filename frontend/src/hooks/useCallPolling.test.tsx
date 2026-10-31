import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CALL_POLL_FAST_MS, CALL_POLL_SLOW_MS, useCallPolling, type CallPollingOptions } from './useCallPolling';

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (hidden ? 'hidden' : 'visible') });
  document.dispatchEvent(new Event('visibilitychange'));
}

const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

function mount(initial: Partial<CallPollingOptions> = {}, refresh = vi.fn(async () => true)) {
  const view = renderHook((o: CallPollingOptions) => useCallPolling(refresh, o), {
    initialProps: { callId: 'call-1', live: false, ended: false, ...initial },
  });
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
    rerender({ callId: 'call-1', live: true, ended: false });
    await tick(CALL_POLL_FAST_MS);
    expect(refresh).toHaveBeenCalledTimes(2);
    rerender({ callId: 'call-1', live: false, ended: false });
    await tick(CALL_POLL_FAST_MS * 5);
    expect(refresh).toHaveBeenCalledTimes(2);
    await tick(CALL_POLL_SLOW_MS);
    expect(refresh).toHaveBeenCalledTimes(3);
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
    const { refresh } = mount({ ended: true, live: true });
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
    await tick(CALL_POLL_SLOW_MS * 6);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('stops polling when the call ends, after one last load', async () => {
    const { refresh, rerender } = mount({ live: true });
    await tick(0);
    await tick(CALL_POLL_FAST_MS * 2);
    expect(refresh).toHaveBeenCalledTimes(3);
    rerender({ callId: 'call-1', live: false, ended: true });
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(4);
    await tick(CALL_POLL_SLOW_MS * 3);
    expect(refresh).toHaveBeenCalledTimes(4);
  });

  it('does nothing without a call id and reloads when the id changes', async () => {
    const { refresh, rerender } = mount({ callId: null });
    await tick(CALL_POLL_SLOW_MS * 2);
    expect(refresh).not.toHaveBeenCalled();
    rerender({ callId: 'call-2', live: false, ended: false });
    await tick(0);
    expect(refresh).toHaveBeenCalledTimes(1);
    rerender({ callId: 'call-3', live: false, ended: false });
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
    const { rerender } = renderHook(({ fn }: { fn: () => Promise<boolean> }) => useCallPolling(fn, { callId: 'call-1', live: true, ended: false }), {
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
