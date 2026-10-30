import { afterEach, describe, expect, it } from 'vitest';
import { ApiError, setCredentials, setFetcher } from './client';
import { getDashboard } from './dashboard';
import { endCall, getQueue, startCall } from './renewals';

afterEach(() => {
  setFetcher((...args) => fetch(...args));
  setCredentials(null);
});

describe('renewals api', () => {
  it('startCall posts the policy id with basic auth', async () => {
    setCredentials({ username: 'analyst', password: 'pw' });
    let seen: { url: string; init: RequestInit } | null = null;
    setFetcher(async (url, init) => {
      seen = { url: String(url), init: init ?? {} };
      return new Response(JSON.stringify({ callId: 'c1', caseId: 'c1', greeting: 'Hello' }), { status: 201 });
    });
    const started = await startCall('POL-1');
    expect(started).toEqual({ callId: 'c1', caseId: 'c1', greeting: 'Hello' });
    expect(seen!.url).toMatch(/\/renewals\/calls$/);
    expect(seen!.init.method).toBe('POST');
    expect(JSON.parse(String(seen!.init.body))).toEqual({ policyId: 'POL-1' });
    expect((seen!.init.headers as Record<string, string>).Authorization).toBe('Basic ' + btoa('analyst:pw'));
  });

  it('getDashboard asks for simulated calls only when told to', async () => {
    const urls: string[] = [];
    setFetcher(async (url) => {
      urls.push(String(url));
      return new Response(JSON.stringify({ kpis: {} }), { status: 200 });
    });
    await getDashboard();
    await getDashboard(true);
    expect(urls[0]).toMatch(/\/renewals\/dashboard$/);
    expect(urls[1]).toMatch(/\/renewals\/dashboard\?includeSimulated=true$/);
  });

  it('a 409 problem surfaces its detail', async () => {
    setFetcher(async () =>
      new Response(JSON.stringify({ title: 'Conflict', status: 409, detail: 'OUTSIDE_CALLING_HOURS' }), {
        status: 409,
        headers: { 'Content-Type': 'application/problem+json' },
      }),
    );
    const err = await startCall('POL-2').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.detail).toBe('OUTSIDE_CALLING_HOURS');
  });

  it('getQueue and endCall hit the renewals endpoints', async () => {
    const urls: string[] = [];
    setFetcher(async (url) => {
      urls.push(String(url));
      return new Response(JSON.stringify(String(url).endsWith('/queue') ? [] : { outcome: 'NO_DECISION' }), { status: 200 });
    });
    expect(await getQueue()).toEqual([]);
    expect(await endCall('c1')).toEqual({ outcome: 'NO_DECISION' });
    expect(urls[0]).toMatch(/\/renewals\/queue$/);
    expect(urls[1]).toMatch(/\/renewals\/calls\/c1\/end$/);
  });
});
