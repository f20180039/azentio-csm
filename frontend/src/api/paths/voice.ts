/** Voice service (backend/voice), relative to VOICE_BASE. */
export const VoicePath = {
  RENEWAL_OFFER: '/api/offer',
  SUPPORT_OFFER: '/support/offer',
  SIM_AUDIO: '/sim/audio',
  TEXT_CALL: '/v1/text-call',
  TEXT_TURN: '/v1/text-turn',
  PHONE_ALLOWED: '/v1/phone/allowed',
  PHONE_CALL: '/v1/phone-call',
  SUPPORT_PHONE_CALL: '/support/phone-call',
  EVAL_LATEST: '/v1/eval/latest',
  LLM_STATUS: '/v1/llm/status',
} as const;

/** What the caller said on one turn (recorded by the voice service), for playback beside the transcript. */
export const turnAudioPath = (callId: string, seq: number) => `/support/calls/${encodeURIComponent(callId)}/turns/${seq}/audio`;

/** Pause or resume a live support call (side talk during a demo). */
export const supportPausePath = (callId: string) => `/support/calls/${encodeURIComponent(callId)}/pause`;

/** Tell the live agent what a reviewer corrected a caller turn to, so a corrected mobile number or date of birth is used. */
export const supportTurnCorrectionPath = (callId: string, seq: number) => `/support/calls/${encodeURIComponent(callId)}/turns/${seq}/correction`;
