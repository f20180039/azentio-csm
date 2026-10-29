import { ApiError } from './errors';
import { get, MOCK_MODE, postJson } from './client';
import { mockRenewals } from './mockRenewals';
import type { CallOutcome, CallView, QueueItem, StartedCall, TextTurnResult } from './types';

export const VOICE_BASE: string =
  (import.meta.env.VITE_VOICE_BASE as string | undefined) ?? 'http://localhost:7861';

async function voicePost<T>(path: string, body: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${VOICE_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError({ status: 0, title: 'Cannot reach the voice service', detail: `Check that it is running at ${VOICE_BASE}.` });
  }
  if (!res.ok) {
    let detail: string | undefined;
    try {
      detail = ((await res.json()) as { detail?: string }).detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError({ status: res.status, title: 'Voice service refused the request', detail });
  }
  return (await res.json()) as T;
}

export function getQueue(): Promise<QueueItem[]> {
  return MOCK_MODE ? mockRenewals.getQueue() : get<QueueItem[]>('/renewals/queue');
}

export function startCall(policyId: string): Promise<StartedCall> {
  return MOCK_MODE ? mockRenewals.startCall(policyId) : postJson<StartedCall>('/renewals/calls', { policyId });
}

export async function getCall(callId: string): Promise<CallView> {
  if (MOCK_MODE) return mockRenewals.getCall(callId);
  const c = await get<CallView>(`/renewals/calls/${callId}`);
  return { ...c, transcript: Array.isArray(c.transcript) ? c.transcript : [], summary: c.summary ?? [] };
}

export function endCall(callId: string): Promise<{ outcome: CallOutcome }> {
  return MOCK_MODE ? mockRenewals.endCall(callId) : postJson(`/renewals/calls/${callId}/end`, {});
}

/** Starts the typed (no-audio) session for a call; idempotent on the voice service. */
export function textCall(callId: string): Promise<{ greeting: string }> {
  return MOCK_MODE ? mockRenewals.textCall(callId) : voicePost('/v1/text-call', { callId });
}

export function textTurn(callId: string, text: string): Promise<TextTurnResult> {
  return MOCK_MODE ? mockRenewals.textTurn(callId, text) : voicePost('/v1/text-turn', { callId, text });
}
