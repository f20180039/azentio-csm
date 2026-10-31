import { useEffect, useRef } from 'react';

/** While something outside this page can change the call (a voice or phone leg, a turn in flight): the transcript follows it closely. */
export const CALL_POLL_FAST_MS = 1000;
/** Otherwise, while the call is still open: another operator's changes stay visible without flooding the API. */
export const CALL_POLL_SLOW_MS = 10_000;

export interface CallPollingOptions {
  /** The call to follow; nothing is requested without one, and a new id loads at once. */
  callId: string | null | undefined;
  /** Something live can change the call from outside this page right now. */
  live: boolean;
  /** The call has ended: it is loaded once more and never polled. */
  ended: boolean;
}

/**
 * Keeps a call page's record fresh: loads it once, then polls at `CALL_POLL_FAST_MS` while `live`, else at
 * `CALL_POLL_SLOW_MS`, never while the tab is hidden (one refresh follows as soon as it is visible again), never after
 * the call has ended, never two at once, and at the slow interval after a failed poll until one succeeds.
 *
 * `refresh` resolves `true` when the call was fetched and `false` when it was not (the page shows the error; this hook only
 * backs off). The latest `refresh` is always the one called, so its identity never restarts the schedule.
 */
export function useCallPolling(refresh: () => Promise<boolean>, { callId, live, ended }: CallPollingOptions): void {
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const liveRef = useRef(live);
  liveRef.current = live;
  const reschedule = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!callId) return;
    let cancelled = false;
    let inFlight = false;
    let slowAfterError = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const clear = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
    };
    const delay = () => (liveRef.current && !slowAfterError ? CALL_POLL_FAST_MS : CALL_POLL_SLOW_MS);
    const schedule = () => {
      clear();
      if (!cancelled && !ended) timer = setTimeout(() => void tick(), delay());
    };
    const tick = async () => {
      timer = undefined;
      if (cancelled || inFlight || document.hidden) return; // a hidden tab resumes from the visibilitychange listener
      inFlight = true;
      let ok = false;
      try {
        ok = await refreshRef.current();
      } catch {
        ok = false;
      }
      inFlight = false;
      if (cancelled) return;
      slowAfterError = !ok;
      schedule();
    };
    const onVisibility = () => {
      if (document.hidden || inFlight) return;
      clear();
      void tick();
    };

    reschedule.current = () => {
      if (timer !== undefined) schedule();
    };
    document.addEventListener('visibilitychange', onVisibility);
    void tick();
    return () => {
      cancelled = true;
      clear();
      reschedule.current = null;
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [callId, ended]);

  // a change in liveness moves the pending poll to the new interval instead of waiting out the old one
  useEffect(() => {
    reschedule.current?.();
  }, [live]);
}
