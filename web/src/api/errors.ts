/** RFC 9457 problem+json, or a synthesised equivalent for non-JSON failures. */
export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail?: string;
  readonly type?: string;
  readonly retryAfter?: number;

  constructor(opts: { status: number; title: string; detail?: string; type?: string; retryAfter?: number }) {
    super(opts.detail ? `${opts.title}: ${opts.detail}` : opts.title);
    this.name = 'ApiError';
    this.status = opts.status;
    this.title = opts.title;
    this.detail = opts.detail;
    this.type = opts.type;
    this.retryAfter = opts.retryAfter;
  }

  get isForbidden() {
    return this.status === 403;
  }
  get isUnauthorized() {
    return this.status === 401;
  }
}

const FALLBACK_TITLES: Record<number, string> = {
  400: 'Request was not valid',
  401: 'Sign in again',
  403: 'Your role cannot do this',
  404: 'Not found',
  409: 'Conflict with the current state',
  413: 'File is too large',
  422: 'File could not be processed',
  429: 'Too many requests',
  500: 'Server error',
  502: 'A downstream service failed',
  503: 'Service unavailable',
};

export async function toApiError(res: Response): Promise<ApiError> {
  const retryHeader = res.headers.get('Retry-After');
  const retryAfter = retryHeader ? Number(retryHeader) : undefined;
  let body: Record<string, unknown> | null = null;
  try {
    const text = await res.text();
    body = text ? (JSON.parse(text) as Record<string, unknown>) : null;
  } catch {
    body = null;
  }
  const title =
    (typeof body?.title === 'string' && body.title) ||
    FALLBACK_TITLES[res.status] ||
    `Request failed (${res.status})`;
  const detail =
    (typeof body?.detail === 'string' && body.detail) ||
    (typeof body?.message === 'string' && body.message) ||
    undefined;
  const type = typeof body?.type === 'string' ? body.type : undefined;
  return new ApiError({ status: res.status, title, detail, type, retryAfter });
}
