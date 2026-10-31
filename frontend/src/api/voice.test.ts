import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ failure: null as unknown }));

vi.mock('@pipecat-ai/client-js', () => ({
  PipecatClient: class {
    connect() {
      return Promise.reject(h.failure);
    }
    disconnect() {
      return Promise.resolve();
    }
  },
}));
vi.mock('@pipecat-ai/small-webrtc-transport', () => ({ SmallWebRTCTransport: class {} }));

const handlers = { onUserText: vi.fn(), onBotText: vi.fn(), onDisconnected: vi.fn(), onError: vi.fn() };

describe('connectVoice failures', () => {
  beforeEach(() => {
    h.failure = null;
  });

  it('maps a 409 from the offer endpoint to the already-live message', async () => {
    h.failure = new Response('{"detail":"CALL_IN_PROGRESS"}', { status: 409 });
    const { connectVoice } = await import('./voice');
    await expect(connectVoice('c1', null, handlers)).rejects.toThrow('This call is already live in another tab or window.');
  });

  it('maps a network failure to the unreachable message with the base url', async () => {
    h.failure = new TypeError('Failed to fetch');
    const { connectVoice } = await import('./voice');
    await expect(connectVoice('c1', null, handlers)).rejects.toThrow(
      "Voice service unreachable at http://localhost:7861. Use 'Type instead' to continue.",
    );
  });
});

describe('isSameRequestUrl', () => {
  it('matches a relative endpoint against the absolute URL a Request object reports', async () => {
    const { isSameRequestUrl } = await import('./voice');
    const abs = new URL('/voice/support/offer', window.location.href).href; // what Request.url reports in a browser
    expect(abs.startsWith('http')).toBe(true);
    expect(isSameRequestUrl(abs, '/voice/support/offer')).toBe(true);
    expect(isSameRequestUrl('/voice/support/offer', '/voice/support/offer')).toBe(true);
    expect(isSameRequestUrl('http://localhost:7861/support/offer', 'http://localhost:7861/support/offer')).toBe(true);
  });

  it('does not match another path or another origin', async () => {
    const { isSameRequestUrl } = await import('./voice');
    expect(isSameRequestUrl('/voice/support/offer', '/voice/api/offer')).toBe(false);
    expect(isSameRequestUrl('http://localhost:7861/support/offer', '/voice/support/offer')).toBe(false);
    expect(isSameRequestUrl('http://other.example/support/offer', 'http://localhost:7861/support/offer')).toBe(false);
  });
});
