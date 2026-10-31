import { useEffect, useRef } from 'react';

/** While something can change the call from outside this page (a voice or phone leg, a turn in flight): the transcript follows it closely. */
export const CALL_POLL_FAST_MS = 1000;
/** Otherwise, while the call is still open: another operator's changes stay visible without flooding the API. */
export const CALL_POLL_SLOW_MS = 10_000;
/** After a live leg ends the record is still being finalised (closing turn, the far side's hang-up): stay fast this long. */
export const CALL_POLL_SETTLE_MS = 6000;
/** A transcript turn newer than this means a leg this page did not start is live: a reload mid-call, a desk's Live row, a second screen. */
export const CALL_RECENT_ACTIVITY_MS = 15_000;

export interface CallPollingOptions {
  /** The call to follow; nothing is requested without one, and a new id loads at once. */
  callId: string | null | undefined;
  /** Something live on this page can change the call right now. */
  live: boolean;
  /** The call has ended: it is never polled (the load that found out is the last one). */
  ended: boolean;
  /** When the record's latest turn was written; a recent one counts as live (see `recentActivity`). */
  lastTurnAt?: string | null;
}

/** True when a turn written at `lastTurnAt` is newer than `CALL_RECENT_ACTIVITY_MS`. */
export function recentActivity(lastTurnAt: string | null | undefined, now = Date.now()): boolean {
  if (!lastTurnAt) return false;
  const at = Date.parse(lastTurnAt);
  return Number.isFinite(at) && now - at < CALL_RECENT_ACTIVITY_MS;
}

/**
 * Keeps a call page's record fresh: loads it once, then polls at `CALL_POLL_FAST_MS` while `live`, for
 * `CALL_POLL_SETTLE_MS` after `live` goes off, or while the record shows recent activity; at `CALL_POLL_SLOW_MS`
 * otherwise; never while the tab is hidden (one refresh follows when it is visible again, if a poll was skipped); never
 * after the call has ended; never two at once; and at the slow interval after a failed poll until one succeeds.
 *
 * `refresh` resolves `true` when the call was fetched and `false` when it was not (the page shows the error; this hook only
 * backs off). The latest `refresh` is always the one called, so its identity never restarts the schedule.
 */
export function useCallPolling(refresh: () => Promise<boolean>, { callId, live, ended, lastTurnAt }: CallPollingOptions): void {
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const liveRef = useRef(live);
  liveRef.current = live;
  const endedRef = useRef(ended);
  endedRef.current = ended;
  const lastTurnAtRef = useRef(lastTurnAt);
  lastTurnAtRef.current = lastTurnAt;
  const settleUntil = useRef(0);
  const wasLive = useRef(live);
  const reschedule = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!callId) return;
    let cancelled = false;
    let started = false; // the first load is pending; liveness changes must not push it out
    let inFlight = false;
    let slowAfterError = false;
    let missed = false; // a poll was skipped because the tab was hidden
    let timer: ReturnType<typeof setTimeout> | undefined;
    settleUntil.current = 0;

    const clear = () => {
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
    };
    const fast = () =>
      !slowAfterError && (liveRef.current || Date.now() < settleUntil.current || recentActivity(lastTurnAtRef.current));
    const schedule = () => {
      clear();
      if (!cancelled && !endedRef.current) timer = setTimeout(() => void tick(), fast() ? CALL_POLL_FAST_MS : CALL_POLL_SLOW_MS);
    };
    const tick = async () => {
      timer = undefined;
      if (cancelled || inFlight) return;
      if (document.hidden) {
        missed = true; // resumes from the visibilitychange listener
        return;
      }
      started = true;
      missed = false;
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
      if (document.hidden || inFlight || !missed) return;
      clear();
      void tick();
    };

    reschedule.current = () => {
      if (started && timer !== undefined) schedule();
    };
    document.addEventListener('visibilitychange', onVisibility);
    timer = setTimeout(() => void tick(), 0); // deferred so StrictMode's rehearsal unmount cancels it instead of fetching twice
    return () => {
      cancelled = true;
      clear();
      reschedule.current = null;
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [callId]);

  // a change in liveness moves the pending poll to the new interval instead of waiting out the old one; a leg that just
  // ended keeps the fast interval for the settle window; an ended call drops its pending poll
  useEffect(() => {
    if (wasLive.current && !live) settleUntil.current = Date.now() + CALL_POLL_SETTLE_MS;
    wasLive.current = live;
    reschedule.current?.();
  }, [live, ended, lastTurnAt]);
}
