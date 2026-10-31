import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SAMPLE_PROFILE, SAMPLE_ROUTED_CALL } from '../api/mockSupport';
import { PHONE_RING_TIMEOUT_MS } from '../api/phone';
import type { SimAudioResult, SupportCall as SupportCallRecord } from '../api/support';
import { ToastProvider } from '../components/Toasts';
import { CALL_POLL_FAST_MS, CALL_POLL_SETTLE_MS, CALL_POLL_SLOW_MS } from '../hooks/useCallPolling';
import { SupportChannel } from '../vocab';
import { SupportCall } from './SupportCall';

const h = vi.hoisted(() => ({
  getCall: vi.fn(),
  simAudio: vi.fn(),
  connectSupportVoice: vi.fn(),
  getCustomerProfile: vi.fn(),
  allowed: { configured: false, numbers: [] as { id: string; masked: string }[] },
  phoneCallId: 'phone-call-poll-1',
}));

vi.mock('../api/support', async (orig) => {
  const real = await orig<typeof import('../api/support')>();
  return { ...real, getCall: h.getCall, simAudio: h.simAudio, connectSupportVoice: h.connectSupportVoice, getCustomerProfile: h.getCustomerProfile };
});
vi.mock('../api/phone', async (orig) => {
  const real = await orig<typeof import('../api/phone')>();
  return {
    ...real,
    getPhoneAllowed: vi.fn(async () => h.allowed),
    placeSupportPhoneCall: vi.fn(async () => ({ call_id: h.phoneCallId, status: 'dialling' })),
  };
});

function mount(path: string) {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/support/new" element={<SupportCall />} />
          <Route path="/support/calls/:callId" element={<SupportCall />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

/** An open call whose turns are all minutes old (the sample's timestamps), so nothing in the record reads as recent. */
const openCall = (): SupportCallRecord => ({ ...structuredClone(SAMPLE_ROUTED_CALL), endedAt: null, outcome: null });
const ago = (ms: number) => new Date(Date.now() - ms).toISOString();
const calls = () => h.getCall.mock.calls.length;
const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
/** Outlives the fast interval kept after a live leg ends. */
const waitSettled = () => tick(CALL_POLL_SETTLE_MS + CALL_POLL_FAST_MS);

beforeEach(() => {
  vi.stubGlobal('MediaStream', class {}); // jsdom has none; the live-speech meter checks `srcObject instanceof MediaStream` on a timer
  vi.useFakeTimers({ shouldAdvanceTime: true });
  Object.values(h).forEach((f) => typeof f === 'function' && f.mockReset());
  h.getCustomerProfile.mockResolvedValue(structuredClone(SAMPLE_PROFILE));
  h.allowed = { configured: false, numbers: [] };
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('SupportCall polling', () => {
  it('polls an open call with nothing live about once every 10 s', async () => {
    const live = openCall();
    h.getCall.mockResolvedValue(live);
    mount(`/support/calls/${live.id}`);
    await screen.findByRole('button', { name: 'End call' });
    const before = calls();
    await tick(CALL_POLL_SLOW_MS / 2);
    expect(calls()).toBe(before);
    await tick(CALL_POLL_SLOW_MS / 2 + 500);
    expect(calls()).toBe(before + 1);
  });

  it('polls every second while the microphone is live, then slowly after Stop', async () => {
    const live = openCall();
    h.getCall.mockResolvedValue(live);
    h.connectSupportVoice.mockResolvedValue({ disconnect: vi.fn().mockResolvedValue(undefined), setMicEnabled: vi.fn() });
    mount(`/support/calls/${live.id}`);
    fireEvent.click(await screen.findByRole('button', { name: 'Reconnect microphone' }));
    await screen.findByText('Microphone live');
    let before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 4);

    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    await screen.findByRole('button', { name: 'Reconnect microphone' });
    await waitSettled();
    before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeLessThanOrEqual(before + 1);
  });

  it('polls every second while uploaded audio is being sent, shows the closing turn within the settle window, then slows down', async () => {
    const live = openCall();
    h.getCall.mockResolvedValue(live);
    let release: ((r: SimAudioResult) => void) | null = null;
    h.simAudio.mockImplementation(() => new Promise<SimAudioResult>((resolve) => (release = resolve)));
    mount(`/support/calls/${live.id}`);
    await screen.findByRole('button', { name: 'End call' });

    fireEvent.click(screen.getByRole('tab', { name: 'Upload audio' }));
    fireEvent.change(screen.getByLabelText('Choose audio files'), { target: { files: [new File(['a'], 'a.wav', { type: 'audio/wav' })] } });
    fireEvent.click(screen.getByRole('button', { name: 'Send 1 file' }));
    await waitFor(() => expect(h.simAudio).toHaveBeenCalledTimes(1));
    let before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 4);

    // the voice service writes the last exchange just before it answers simAudio: the record catches up after the upload
    const closing = { ...live.turns[live.turns.length - 1], seq: live.turns.length + 1, text: 'Anything else I can help with today?' };
    h.getCall.mockResolvedValue({ ...live, turns: [...live.turns, closing] });
    await act(async () => release!({ call_id: live.id, turns: [] }));
    await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument());
    await tick(CALL_POLL_FAST_MS * 2);
    expect(screen.getByText(closing.text)).toBeInTheDocument(); // not 10 s later

    await waitSettled();
    before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeLessThanOrEqual(before + 1);
  });

  it('polls fast for an open call opened from the desk whose latest turn is recent (a leg this page did not start)', async () => {
    const live = openCall();
    live.turns[live.turns.length - 1].at = ago(5000);
    h.getCall.mockResolvedValue(live);
    mount(`/support/calls/${live.id}`);
    await screen.findByRole('button', { name: 'End call' });
    const before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 4);
  });

  it('polls fast for an open, answered phone call opened directly, whatever the age of its turns', async () => {
    const live: SupportCallRecord = { ...openCall(), channel: SupportChannel.PHONE };
    h.getCall.mockResolvedValue(live);
    mount(`/support/calls/${live.id}`);
    await screen.findByRole('button', { name: 'End call' });
    const before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 4);
  });

  it('polls every second after the desk rings a phone, and keeps doing so once the caller answers', async () => {
    h.allowed = { configured: true, numbers: [{ id: '0', masked: '+91 ••••• •4417' }] };
    const ringing: SupportCallRecord = { ...openCall(), id: h.phoneCallId, channel: SupportChannel.PHONE, turns: [] };
    h.getCall.mockResolvedValue(ringing);
    mount('/support/new');
    fireEvent.click(await screen.findByRole('button', { name: 'Call a phone' }));
    await screen.findByText(h.phoneCallId);
    let before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 4);

    h.getCall.mockResolvedValue({ ...ringing, turns: openCall().turns });
    await tick(CALL_POLL_FAST_MS * 2);
    await screen.findByRole('log', { name: 'Conversation history' });
    await tick(PHONE_RING_TIMEOUT_MS); // well past the ring window: answered calls stay fast until they end
    before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeGreaterThanOrEqual(before + 4);
  });

  it('slows down when a rung phone is never answered', async () => {
    h.allowed = { configured: true, numbers: [{ id: '0', masked: '+91 ••••• •4417' }] };
    h.getCall.mockResolvedValue({ ...openCall(), id: h.phoneCallId, channel: SupportChannel.PHONE, turns: [] });
    mount('/support/new');
    fireEvent.click(await screen.findByRole('button', { name: 'Call a phone' }));
    await screen.findByText(h.phoneCallId);
    await tick(PHONE_RING_TIMEOUT_MS);
    await waitSettled();
    const before = calls();
    await tick(CALL_POLL_FAST_MS * 5);
    expect(calls()).toBeLessThanOrEqual(before + 1);
  });

  it('loads an ended call once and never polls it', async () => {
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_ROUTED_CALL));
    mount(`/support/calls/${SAMPLE_ROUTED_CALL.id}`);
    await screen.findByText('Routed');
    await tick(300);
    const before = calls();
    await tick(CALL_POLL_SLOW_MS * 3);
    expect(calls()).toBe(before);
  });
});
