import { MOCK_MODE } from './client';
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

/** Numbers the voice service may dial, masked; the real numbers never reach the browser. */
export async function getPhoneAllowed(): Promise<PhoneAllowed> {
  if (MOCK_MODE) return OFF;
  try {
    const res = await fetch(`${VOICE_BASE}/v1/phone/allowed`);
    return res.ok ? ((await res.json()) as PhoneAllowed) : OFF;
  } catch {
    return OFF;
  }
}

export function placePhoneCall(callId: string, numberId: string): Promise<{ status: string }> {
  return voicePost('/v1/phone-call', { callId, numberId });
}
