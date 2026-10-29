import { afterEach, describe, expect, it, vi } from 'vitest';
import { getPhoneAllowed, placePhoneCall } from './phone';

afterEach(() => vi.unstubAllGlobals());

describe('getPhoneAllowed', () => {
  it('returns the masked numbers the voice service reports', async () => {
    const body = { configured: true, numbers: [{ id: '0', masked: '+91 ••••• •4417' }] };
    const f = vi.fn(async (_url: string) => new Response(JSON.stringify(body), { status: 200 }));
    vi.stubGlobal('fetch', f);
    expect(await getPhoneAllowed()).toEqual(body);
    expect(String(f.mock.calls[0][0])).toMatch(/\/v1\/phone\/allowed$/);
  });

  it('reads an unreachable voice service as not configured', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    expect(await getPhoneAllowed()).toEqual({ configured: false, numbers: [] });
  });
});

describe('placePhoneCall', () => {
  it('posts the call id and the number id, never a raw number', async () => {
    const f = vi.fn(async (_url: string, _init?: RequestInit) => new Response('{"twilioCallSid":"CA1"}', { status: 200 }));
    vi.stubGlobal('fetch', f);
    expect(await placePhoneCall('c-1', '0')).toEqual({ twilioCallSid: 'CA1' });
    expect(String(f.mock.calls[0][0])).toMatch(/\/v1\/phone-call$/);
    expect(JSON.parse(String(f.mock.calls[0][1]?.body))).toEqual({ callId: 'c-1', numberId: '0' });
  });

  it('surfaces the refusal detail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"PHONE_NOT_CONFIGURED"}', { status: 503 })));
    await expect(placePhoneCall('c-1', '0')).rejects.toMatchObject({ status: 503 });
  });
});
