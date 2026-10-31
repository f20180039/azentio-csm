const Path = {
  SUPPORT: '/support',
  SUPPORT_NEW: '/support/new',
  SUPPORT_INSIGHTS: '/support/insights',
  SUPPORT_CALL: '/support/calls/:callId',
  DASHBOARD: '/dashboard',
  QUEUE: '/queue',
  CASE: '/cases/:id',
  RENEWALS: '/renewals',
  RENEWAL_CALL: '/renewals/calls/:callId',
  PACKS: '/packs',
} as const;
export type RoutePath = (typeof Path)[keyof typeof Path];

const fill = (pattern: RoutePath, param: string, value: string) => pattern.replace(`:${param}`, () => value);

export const Route = {
  ...Path,
  supportCall: (callId: string) => fill(Path.SUPPORT_CALL, 'callId', encodeURIComponent(callId)),
  renewalCall: (callId: string) => fill(Path.RENEWAL_CALL, 'callId', callId),
  case: (id: string) => fill(Path.CASE, 'id', id),
} as const;
