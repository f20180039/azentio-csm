import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setCredentials } from '../api/client';
import { SAMPLE_PII, SAMPLE_PROFILE, SAMPLE_ROUTED_CALL, SAMPLE_VERIFIED_CALL } from '../api/mockSupport';
import type { PiiTokens, SimAudioResult, SupportCall as SupportCallRecord } from '../api/support';
import { ToastProvider } from '../components/Toasts';
import { SupportCall } from './SupportCall';

const h = vi.hoisted(() => ({
  getCall: vi.fn(),
  simAudio: vi.fn(),
  connectSupportVoice: vi.fn(),
  endCall: vi.fn(),
  pauseCall: vi.fn(),
  getCustomerProfile: vi.fn(),
  getCallPii: vi.fn(),
}));

vi.mock('../api/support', async (orig) => {
  const real = await orig<typeof import('../api/support')>();
  return { ...real, getCall: h.getCall, simAudio: h.simAudio, connectSupportVoice: h.connectSupportVoice, endCall: h.endCall, pauseCall: h.pauseCall,
    getCustomerProfile: h.getCustomerProfile, getCallPii: h.getCallPii };
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

beforeEach(() => {
  Object.values(h).forEach((f) => f.mockReset());
  h.getCustomerProfile.mockResolvedValue(structuredClone(SAMPLE_PROFILE));
});

describe('SupportCall', () => {
  it('shows intent chips, the verified badge, a Retrieved card and the ticket ref from the call record', async () => {
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_VERIFIED_CALL));
    mount(`/support/calls/${SAMPLE_VERIFIED_CALL.id}`);

    const badge = await screen.findByTestId('verification');
    expect(badge).toHaveTextContent('Verified');
    expect(badge).toHaveAttribute('data-state', 'VERIFIED');

    const log = screen.getByRole('log', { name: 'Conversation history' });
    const repayment = within(log).getAllByText('Repayment');
    expect(repayment.length).toBeGreaterThan(0);
    expect(repayment[0]).toHaveAttribute('title', 'REPAYMENT');
    expect(within(log).getByText('Service request')).toHaveAttribute('title', 'SERVICE_REQUEST');

    expect(within(log).getAllByText(/^Retrieved/).length).toBe(4);
    expect(within(log).getAllByText('create_service_request').length).toBeGreaterThan(0);
    expect(within(log).getAllByText('SR-40200').filter((e) => e.classList.contains('ref-pill'))).toHaveLength(1);
    expect(screen.getByText('Ticket created')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'End call' })).not.toBeInTheDocument();
  });

  it('marks no-speech turns and polls a live call every second until it ends', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const live: SupportCallRecord = { ...structuredClone(SAMPLE_ROUTED_CALL), endedAt: null, outcome: null };
      h.getCall.mockResolvedValue(live);
      mount(`/support/calls/${live.id}`);
      expect(await screen.findByText('No speech detected')).toBeInTheDocument();
      expect(screen.getByTestId('verification')).toHaveAttribute('data-state', 'NOT_VERIFIED');
      expect(within(screen.getByRole('log')).getByText('Unsupported')).toHaveAttribute('title', 'UNSUPPORTED');

      const before = h.getCall.mock.calls.length;
      await vi.advanceTimersByTimeAsync(2100);
      expect(h.getCall.mock.calls.length).toBeGreaterThanOrEqual(before + 2);

      h.getCall.mockResolvedValue({ ...live, endedAt: new Date().toISOString(), outcome: 'ROUTED' });
      await vi.advanceTimersByTimeAsync(1100);
      await waitFor(() => expect(screen.getByText('Routed')).toBeInTheDocument());
      await vi.advanceTimersByTimeAsync(1100); // let a poll already in flight when the call ended finish before counting
      const settled = h.getCall.mock.calls.length;
      await vi.advanceTimersByTimeAsync(3000);
      expect(h.getCall.mock.calls.length).toBe(settled);
    } finally {
      vi.useRealTimers();
    }
  });

  it('upload tab posts each file to simAudio in order and renders the returned turns', async () => {
    const first: SimAudioResult = {
      call_id: 'call-up-1',
      turns: [{ file: 'a.wav', transcript: 'When is my next EMI?', no_speech: false, intents: ['REPAYMENT'], verified: false, tool_trace: [], retrieved: {}, reply_text: 'Please tell me your mobile number and date of birth.', reply_audio_b64: 'UklGRgAAAA==' }],
    };
    const second: SimAudioResult = {
      call_id: 'call-up-1',
      turns: [{ file: 'b.wav', transcript: '', no_speech: true, intents: [], verified: false, tool_trace: [], retrieved: {}, reply_text: null, reply_audio_b64: null }],
    };
    h.simAudio.mockResolvedValueOnce(first).mockResolvedValueOnce(second);
    h.getCall.mockRejectedValue(new Error('not recorded yet'));
    mount('/support/new');

    fireEvent.click(screen.getByRole('tab', { name: 'Upload audio' }));
    const a = new File(['a'], 'a.wav', { type: 'audio/wav' });
    const b = new File(['b'], 'b.wav', { type: 'audio/wav' });
    fireEvent.change(screen.getByLabelText('Choose audio files'), { target: { files: [a, b] } });
    expect(within(screen.getByRole('list', { name: 'Files to send' })).getAllByRole('listitem')).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: 'Send 2 files' }));
    await waitFor(() => expect(h.simAudio).toHaveBeenCalledTimes(2));
    expect(h.simAudio.mock.calls[0]).toEqual([[a], undefined]);
    expect(h.simAudio.mock.calls[1]).toEqual([[b], 'call-up-1']);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    expect(await within(log).findByText('When is my next EMI?')).toBeInTheDocument();
    expect(within(log).getByText('Please tell me your mobile number and date of birth.')).toBeInTheDocument();
    expect(within(log).getByText('No speech detected')).toBeInTheDocument();
    expect(screen.getByLabelText('Reply to a.wav')).toHaveAttribute('src', 'data:audio/wav;base64,UklGRgAAAA==');
  });

  it('ending an already-ended call closes the dialog without showing conflict error', async () => {
    const live: SupportCallRecord = { ...structuredClone(SAMPLE_ROUTED_CALL), endedAt: null, outcome: null };
    h.getCall.mockResolvedValue(live);
    const { ApiError } = await import('../api/errors');
    h.endCall.mockRejectedValue(new ApiError({ status: 409, title: 'Conflict', detail: 'CALL_ALREADY_ENDED' }));
    mount(`/support/calls/${live.id}`);

    const endBtn = await screen.findByRole('button', { name: 'End call' });
    fireEvent.click(endBtn);

    const dialog = screen.getByRole('dialog', { name: 'End this call' });
    expect(dialog).toBeInTheDocument();

    const confirmBtn = within(dialog).getByRole('button', { name: 'End call' });
    fireEvent.click(confirmBtn);

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.queryByText('CALL_ALREADY_ENDED')).not.toBeInTheDocument();
  });
});

describe('customer turn playback', () => {
  it('pauses for side talk by muting the mic before telling the agent, then resumes and stops', async () => {
    const live: SupportCallRecord = { ...structuredClone(SAMPLE_ROUTED_CALL), endedAt: null, outcome: null };
    h.getCall.mockResolvedValue(live);
    const order: string[] = [];
    const session = {
      disconnect: vi.fn().mockResolvedValue(undefined),
      setMicEnabled: vi.fn((on: boolean) => order.push(`mic:${on}`)),
    };
    h.connectSupportVoice.mockResolvedValue(session);
    h.pauseCall.mockImplementation(async (_id: string, on: boolean) => {
      order.push(`server:${on}`);
    });
    mount(`/support/calls/${live.id}`);

    fireEvent.click(await screen.findByRole('button', { name: 'Reconnect microphone' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Pause' }));
    await screen.findByRole('button', { name: 'Resume' });
    expect(screen.getByText('Paused: the agent isn’t listening')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    await screen.findByRole('button', { name: 'Pause' });
    expect(order).toEqual(['mic:false', 'server:true', 'server:false', 'mic:true']);
    expect(h.pauseCall).toHaveBeenCalledWith(live.id, true);

    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    await screen.findByRole('button', { name: 'Reconnect microphone' });
    expect(session.disconnect).toHaveBeenCalled();
  });

  it('follows the new call when the microphone starts one from a page showing another call', async () => {
    const live: SupportCallRecord = { ...structuredClone(SAMPLE_ROUTED_CALL), endedAt: null, outcome: null };
    const fresh: SupportCallRecord = { ...live, id: '99999999-9999-9999-9999-999999999999', turns: [] };
    h.getCall.mockImplementation(async (id: string) => (id === fresh.id ? fresh : live));
    h.connectSupportVoice.mockImplementation(async (_id: string, _a: unknown, handlers: { onCallId: (id: string) => void }) => {
      handlers.onCallId(fresh.id);
      return { disconnect: vi.fn().mockResolvedValue(undefined), setMicEnabled: vi.fn() };
    });
    mount(`/support/calls/${live.id}`);

    fireEvent.click(await screen.findByRole('button', { name: 'Reconnect microphone' }));
    await waitFor(() => expect(h.getCall).toHaveBeenCalledWith(fresh.id));
    expect(screen.getByText(fresh.id)).toBeInTheDocument();
  });

  it('unmutes the mic again when the agent could not be paused', async () => {
    const live: SupportCallRecord = { ...structuredClone(SAMPLE_ROUTED_CALL), endedAt: null, outcome: null };
    h.getCall.mockResolvedValue(live);
    const session = { disconnect: vi.fn().mockResolvedValue(undefined), setMicEnabled: vi.fn() };
    h.connectSupportVoice.mockResolvedValue(session);
    h.pauseCall.mockRejectedValue(new Error('voice service down'));
    mount(`/support/calls/${live.id}`);

    fireEvent.click(await screen.findByRole('button', { name: 'Reconnect microphone' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(session.setMicEnabled).toHaveBeenLastCalledWith(true));
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument();
  });

  it('shows the verified caller\'s bank profile, and a hint before verification', async () => {
    h.getCustomerProfile.mockResolvedValue(structuredClone(SAMPLE_PROFILE));
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_VERIFIED_CALL));
    mount(`/support/calls/${SAMPLE_VERIFIED_CALL.id}`);
    const card = within(await screen.findByRole('region', { name: 'Customer' }));
    expect(await card.findByText('Rahul Iyer')).toBeInTheDocument();
    expect(card.getByText('98765 00002')).toBeInTheDocument();
    expect(h.getCustomerProfile).toHaveBeenCalledWith('CUST-1002');
  });

  it('asks for verification first when the caller is not verified yet', async () => {
    h.getCall.mockResolvedValue({ ...structuredClone(SAMPLE_ROUTED_CALL), endedAt: null, outcome: null });
    mount(`/support/calls/${SAMPLE_ROUTED_CALL.id}`);
    const card = within(await screen.findByRole('region', { name: 'Customer' }));
    expect(card.getByText(/once the agent has verified them/)).toBeInTheDocument();
    expect(h.getCustomerProfile).not.toHaveBeenCalled();
  });

  it('builds the voice service URL for a recorded turn', async () => {
    const { turnAudioUrl } = await import('../api/support');
    expect(turnAudioUrl('11111111-1111-1111-1111-111111111111', 3)).toMatch(/\/support\/calls\/11111111-1111-1111-1111-111111111111\/turns\/3\/audio$/);
  });
});

describe('personal data on the call screen', () => {
  const MOBILE = '9876500002';
  const TOGGLE = /personal data/;

  afterEach(() => setCredentials(null));

  it('shows tokens as redacted chips and no reveal toggle for an analyst', async () => {
    setCredentials({ username: 'analyst', password: 'analyst' });
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_VERIFIED_CALL));
    mount(`/support/calls/${SAMPLE_VERIFIED_CALL.id}`);

    const log = within(await screen.findByRole('log', { name: 'Conversation history' }));
    expect(log.getAllByText('Mobile (redacted)').length).toBeGreaterThan(0);
    expect(log.getAllByText('Date of birth (redacted)').length).toBeGreaterThan(0);
    expect(log.queryByText(/\[MOBILE#1\]/, { ignore: 'pre' })).not.toBeInTheDocument(); // only the Raw JSON dump keeps the token
    expect(screen.queryByText(MOBILE)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: TOGGLE })).not.toBeInTheDocument();
    expect(h.getCallPii).not.toHaveBeenCalled();
  });

  it('lets an admin reveal the values once, holds them only in memory, and drops them when toggled off', async () => {
    setCredentials({ username: 'admin', password: 'admin' });
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_VERIFIED_CALL));
    h.getCallPii.mockResolvedValue(structuredClone(SAMPLE_PII[SAMPLE_VERIFIED_CALL.id]));
    const localSet = vi.spyOn(Storage.prototype, 'setItem');
    mount(`/support/calls/${SAMPLE_VERIFIED_CALL.id}`);

    const show = await screen.findByRole('button', { name: 'Show personal data' });
    expect(show).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByText(MOBILE)).not.toBeInTheDocument();

    fireEvent.click(show);
    const log = within(await screen.findByRole('log', { name: 'Conversation history' }));
    expect((await log.findAllByText(MOBILE)).length).toBeGreaterThan(0);
    expect(log.getAllByText('1985-11-03').length).toBeGreaterThan(0);
    expect(log.queryByText('Mobile (redacted)')).not.toBeInTheDocument();
    expect(h.getCallPii).toHaveBeenCalledTimes(1);
    expect(h.getCallPii).toHaveBeenCalledWith(SAMPLE_VERIFIED_CALL.id);
    const hide = screen.getByRole('button', { name: 'Hide personal data' });
    expect(hide).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(hide);
    await waitFor(() => expect(screen.queryByText(MOBILE)).not.toBeInTheDocument());
    expect(log.getAllByText('Mobile (redacted)').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Show personal data' })).toBeInTheDocument();
    expect(h.getCallPii).toHaveBeenCalledTimes(1);
    expect(localSet).not.toHaveBeenCalled();
    localSet.mockRestore();
  });

  it('drops a reveal that resolves after the admin has moved on to another call', async () => {
    setCredentials({ username: 'admin', password: 'admin' });
    const a = structuredClone(SAMPLE_VERIFIED_CALL);
    const b: SupportCallRecord = { ...structuredClone(SAMPLE_VERIFIED_CALL), id: 'sample-call-other-customer' };
    h.getCall.mockImplementation(async (id: string) => (id === b.id ? b : a));
    let resolveA!: (tokens: PiiTokens) => void;
    h.getCallPii.mockReturnValue(new Promise<PiiTokens>((r) => { resolveA = r; }));
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    render(
      <ToastProvider>
        <MemoryRouter initialEntries={[`/support/calls/${a.id}`]}>
          <Routes>
            <Route
              path="/support/calls/:callId"
              element={
                <>
                  <SupportCall />
                  <Link to={`/support/calls/${b.id}`}>Open call B</Link>
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </ToastProvider>,
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Show personal data' }));
    expect(h.getCallPii).toHaveBeenCalledWith(a.id);
    expect(screen.getByRole('button', { name: 'Revealing…' })).toBeDisabled();

    fireEvent.click(screen.getByRole('link', { name: 'Open call B' }));
    await screen.findByText(b.id);
    expect(screen.getByRole('button', { name: 'Show personal data' })).not.toBeDisabled(); // B starts redacted, not "revealing"

    resolveA(structuredClone(SAMPLE_PII[a.id]));
    await waitFor(() => expect(h.getCall).toHaveBeenCalledWith(b.id));
    await new Promise((r) => setTimeout(r, 0)); // let the late response settle
    const log = within(screen.getByRole('log', { name: 'Conversation history' }));
    expect(log.getAllByText('Mobile (redacted)').length).toBeGreaterThan(0);
    expect(screen.queryByText(MOBILE)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show personal data' })).toHaveAttribute('aria-pressed', 'false');
    expect(h.getCallPii).toHaveBeenCalledTimes(1);
  });

  it('reveals personal data inside tool arguments too', async () => {
    setCredentials({ username: 'admin', password: 'admin' });
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_VERIFIED_CALL));
    h.getCallPii.mockResolvedValue(structuredClone(SAMPLE_PII[SAMPLE_VERIFIED_CALL.id]));
    mount(`/support/calls/${SAMPLE_VERIFIED_CALL.id}`);

    fireEvent.click(await screen.findByRole('button', { name: 'Show personal data' }));
    const log = within(await screen.findByRole('log', { name: 'Conversation history' }));
    await waitFor(() => expect(log.getAllByText(MOBILE).length).toBeGreaterThanOrEqual(2));
  });
});
