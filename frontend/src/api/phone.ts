import { MOCK_MODE } from './client';
import { VoicePath } from './paths/voice';
import { VOICE_BASE, voicePost } from './renewals';

export interface PhoneNumber {
  id: string;
  masked: string;
}

export interface PhoneAllowed {
  configured: boolean;
  numbers: PhoneNumber[];
}

const OFF: PhoneAllowed = { configured: false, numbers: [] };

/** The voice service forgets an unanswered dial after this long (its PENDING_TTL_SECS), so a page stops waiting for it too. */
export const PHONE_RING_TIMEOUT_MS = 120_000;

/** Numbers the voice service may dial, masked; the real numbers never reach the browser. */
export async function getPhoneAllowed(): Promise<PhoneAllowed> {
  if (MOCK_MODE) return OFF;
  try {
    const res = await fetch(`${VOICE_BASE}${VoicePath.PHONE_ALLOWED}`);
    return res.ok ? ((await res.json()) as PhoneAllowed) : OFF;
  } catch {
    return OFF;
  }
}

export function placePhoneCall(callId: string, numberId: string): Promise<{ status: string }> {
  return voicePost(VoicePath.PHONE_CALL, { callId, numberId });
}

/** Rings an allowed number; the answered call is a new PHONE support call with the front-desk agent. */
export function placeSupportPhoneCall(numberId: string): Promise<{ call_id: string; status: string }> {
  return voicePost(VoicePath.SUPPORT_PHONE_CALL, { numberId });
}
