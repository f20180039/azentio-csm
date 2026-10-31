/** Voice service (backend/voice), relative to VOICE_BASE. */
export const VoicePath = {
  RENEWAL_OFFER: '/api/offer',
  SUPPORT_OFFER: '/support/offer',
  SIM_AUDIO: '/sim/audio',
  TEXT_CALL: '/v1/text-call',
  TEXT_TURN: '/v1/text-turn',
  PHONE_ALLOWED: '/v1/phone/allowed',
  PHONE_CALL: '/v1/phone-call',
  EVAL_LATEST: '/v1/eval/latest',
  LLM_STATUS: '/v1/llm/status',
} as const;
