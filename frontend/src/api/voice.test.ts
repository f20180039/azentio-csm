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
