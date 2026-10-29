import { afterEach, describe, expect, it } from 'vitest';
import { ApiError, api, normalisePack, normalisePage, setCredentials, setFetcher, toApiError } from './client';

function respond(status: number, body: string, headers: Record<string, string> = {}) {
  return new Response(body, { status, headers });
}

afterEach(() => {
  setFetcher((...args) => fetch(...args));
  setCredentials(null);
});

describe('toApiError', () => {
  it('reads RFC 9457 problem+json fields', async () => {
    const err = await toApiError(
      respond(403, JSON.stringify({ type: 'urn:problem:forbidden', title: 'Forbidden', status: 403, detail: 'Needs REVIEWER' }), {
        'Content-Type': 'application/problem+json',
      }),
    );
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(403);
    expect(err.isForbidden).toBe(true);
    expect(err.title).toBe('Forbidden');
    expect(err.detail).toBe('Needs REVIEWER');
    expect(err.type).toBe('urn:problem:forbidden');
  });

  it('falls back to a readable title when the body is not JSON', async () => {
    const err = await toApiError(respond(502, '<html>Bad gateway</html>'));
    expect(err.title).toBe('A downstream service failed');
    expect(err.detail).toBeUndefined();
  });

  it('captures Retry-After on 429', async () => {
    const err = await toApiError(respond(429, '', { 'Retry-After': '12' }));
    expect(err.title).toBe('Too many requests');
    expect(err.retryAfter).toBe(12);
  });
});

describe('api client', () => {
  it('sends Basic auth and surfaces a 403 as ApiError', async () => {
    let seenAuth: string | null = null;
    setCredentials({ username: 'analyst', password: 'analyst' });
    setFetcher(async (_url, init) => {
      seenAuth = new Headers(init?.headers).get('Authorization');
      return respond(403, JSON.stringify({ title: 'Forbidden', status: 403, detail: 'Needs REVIEWER' }));
    });
    await expect(api.decideCase('c1', { action: 'APPROVE', reason: 'ok' })).rejects.toMatchObject({ status: 403, detail: 'Needs REVIEWER' });
    expect(seenAuth).toBe('Basic ' + btoa('analyst:analyst'));
  });

  it('turns a network failure into a status-0 ApiError', async () => {
    setFetcher(async () => {
      throw new TypeError('Failed to fetch');
    });
    await expect(api.getStats()).rejects.toMatchObject({ status: 0, title: 'Cannot reach the API' });
  });

  it('reports cache HIT from the X-Cache header on upload', async () => {
    setFetcher(async () =>
      respond(200, JSON.stringify({ id: 'c9', caseType: 'demo', title: 't', status: 'NEEDS_REVIEW', riskScore: 0.3, amountAtRisk: 0, createdAt: '2026-10-28T00:00:00Z' }), {
        'X-Cache': 'HIT',
      }),
    );
    const r = await api.uploadCase([new File(['x'], 'a.pdf')], 'demo');
    expect(r.cache).toBe('HIT');
    expect(r.case.findingsCount).toBe(0);
  });
});

describe('normalisers', () => {
  it('accepts arrays and Spring pages', () => {
    expect(normalisePage([1, 2]).total).toBe(2);
    expect(normalisePage({ content: [1], totalElements: 9 })).toEqual({ items: [1], total: 9 });
  });

  it('turns a rules map into a list', () => {
    const p = normalisePack({ caseType: 'demo', rules: { 'CORE-X': { weight: 0.5, rationale: 'r' } } });
    expect(p.rules).toEqual([{ id: 'CORE-X', weight: 0.5, rationale: 'r' }]);
  });
});
