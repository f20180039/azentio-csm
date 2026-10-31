import { afterEach, describe, expect, it, vi } from 'vitest';
import { getEvalLatest } from './eval';

afterEach(() => vi.unstubAllGlobals());

describe('getEvalLatest', () => {
  it('returns null when no run exists', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"none"}', { status: 404 })));
    expect(await getEvalLatest()).toBeNull();
  });

  it('returns the report from the voice service', async () => {
    const f = vi.fn(async (_url: string) => new Response('{"totals":{"conversations":18}}', { status: 200 }));
    vi.stubGlobal('fetch', f);
    expect(await getEvalLatest()).toEqual({ totals: { conversations: 18 } });
    expect(String(f.mock.calls[0][0])).toMatch(/\/v1\/eval\/latest$/);
  });

  it('throws on other failures', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 500 })));
    await expect(getEvalLatest()).rejects.toThrow(/could not be loaded/);
  });
});
