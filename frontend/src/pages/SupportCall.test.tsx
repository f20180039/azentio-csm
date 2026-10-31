import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SAMPLE_ROUTED_CALL, SAMPLE_VERIFIED_CALL } from '../api/mockSupport';
import type { SimAudioResult, SupportCall as SupportCallRecord } from '../api/support';
import { ToastProvider } from '../components/Toasts';
import { SupportCall } from './SupportCall';

const h = vi.hoisted(() => ({
  getCall: vi.fn(),
  simAudio: vi.fn(),
  connectSupportVoice: vi.fn(),
  endCall: vi.fn(),
}));

vi.mock('../api/support', async (orig) => {
  const real = await orig<typeof import('../api/support')>();
  return { ...real, getCall: h.getCall, simAudio: h.simAudio, connectSupportVoice: h.connectSupportVoice, endCall: h.endCall };
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
  it('builds the voice service URL for a recorded turn', async () => {
    const { turnAudioUrl } = await import('../api/support');
    expect(turnAudioUrl('11111111-1111-1111-1111-111111111111', 3)).toMatch(/\/support\/calls\/11111111-1111-1111-1111-111111111111\/turns\/3\/audio$/);
  });
});
