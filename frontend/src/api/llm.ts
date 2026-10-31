import { MOCK_MODE } from './client';
import { VOICE_BASE } from './renewals';

export interface LlmLink {
  name: string;
  available: boolean;
  cooldownUntil: string | null;
  lastError: string | null;
}

export interface LlmStatus {
  active: string | null;
  links: LlmLink[];
}

/** The voice agent's model chain, or null when the voice service can't say. */
export async function getLlmStatus(): Promise<LlmStatus | null> {
  if (MOCK_MODE) return null;
  try {
    const res = await fetch(`${VOICE_BASE}/v1/llm/status`);
    return res.ok ? ((await res.json()) as LlmStatus) : null;
  } catch {
    return null;
  }
}
