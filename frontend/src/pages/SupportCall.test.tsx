import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SAMPLE_ESCALATION_CALL, SAMPLE_PROFILE, SAMPLE_ROUTED_CALL, SAMPLE_VERIFIED_CALL } from '../api/mockSupport';
import type { SimAudioResult, SupportCall as SupportCallRecord } from '../api/support';
import { ToastProvider } from '../components/Toasts';
import { displayName } from '../demoUsers';
import { SessionProvider } from '../session';
import { RetrievedCard, SupportCall } from './SupportCall';
import { OpOutcome, Role, TurnRole } from '../vocab';

const h = vi.hoisted(() => ({
  getCall: vi.fn(),
  simAudio: vi.fn(),
  connectSupportVoice: vi.fn(),
  endCall: vi.fn(),
  pauseCall: vi.fn(),
  getCustomerProfile: vi.fn(),
  correctTranscript: vi.fn(),
  clearTranscriptCorrection: vi.fn(),
}));

vi.mock('../api/support', async (orig) => {
  const real = await orig<typeof import('../api/support')>();
  return { ...real, getCall: h.getCall, simAudio: h.simAudio, connectSupportVoice: h.connectSupportVoice, endCall: h.endCall, pauseCall: h.pauseCall,
    getCustomerProfile: h.getCustomerProfile, correctTranscript: h.correctTranscript, clearTranscriptCorrection: h.clearTranscriptCorrection };
});

/** With `roles`, the page is signed in as that role (the first one names the user); without, there is no session. */
function mount(path: string, roles?: Role[]) {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  const page = (
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/support/new" element={<SupportCall />} />
        <Route path="/support/calls/:callId" element={<SupportCall />} />
      </Routes>
    </MemoryRouter>
  );
  return render(
    <ToastProvider>
      {roles ? <SessionProvider initial={{ username: roles[0].toLowerCase(), password: 'x', roles }}>{page}</SessionProvider> : page}
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

describe('RetrievedCard outcomes', () => {
  it('marks a failed tool call bad and a declined one dim, and leaves old records without an outcome alone', () => {
    render(
      <RetrievedCard
        trace={[
          { name: 'create_service_request', args: {}, result_summary: 'SYSTEM_UNAVAILABLE', outcome: OpOutcome.FAILED },
          { name: 'get_loans', args: {}, result_summary: 'NOT_VERIFIED', outcome: OpOutcome.DECLINED },
          { name: 'verify_customer', args: {}, result_summary: 'Verified CUST-1002', outcome: OpOutcome.OK },
          { name: 'get_faq', args: {}, result_summary: 'legacy record' },
        ]}
        retrieved={{}}
        refs={[]}
      />,
    );
    expect(screen.getByText('Failed')).toHaveClass('pill', 'bad');
    expect(screen.getByText('Declined')).toHaveClass('pill', 'dim');
    expect(screen.getByText('OK')).toHaveClass('pill', 'ok');
    expect(screen.getAllByText(/^(Failed|Declined|OK)$/)).toHaveLength(3);
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

describe('English beside Kannada and Hindi turns', () => {
  const KANNADA_ASK = 'ನನ್ನ ಮುಂದಿನ ಇಎಂಐ ಯಾವಾಗ?';
  const ESCALATION_ASK = 'There is a card payment of 48,999 rupees I never made.';

  it('shows the language chip and the English, labelled, under a Kannada turn', async () => {
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_ESCALATION_CALL));
    mount(`/support/calls/${SAMPLE_ESCALATION_CALL.id}`);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const original = await within(log).findByText(KANNADA_ASK);
    expect(original).toHaveAttribute('lang', 'kn');
    expect(original).not.toHaveClass('muted');
    const turn = original.closest('li')!;
    expect(within(turn).getByText('Kannada')).toHaveClass('pill');

    const english = within(turn).getByTestId('turn-english');
    expect(english).toHaveTextContent('English: When is my next EMI?');
    expect(english).toHaveClass('muted');
    expect(english).toHaveAttribute('lang', 'en');
    expect(original.compareDocumentPosition(english) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // An English turn gets neither a chip nor a second line. (The Retrieved card quotes the complaint statement too, so match the turn's own line.)
    const englishTurn = within(log).getByText(ESCALATION_ASK, { selector: '.sc-turn.customer > p' }).closest('li')!;
    expect(within(englishTurn).queryByText('Kannada')).toBeNull();
    expect(within(englishTurn).queryByTestId('turn-english')).toBeNull();
  });

  it('"English first" puts the English line first and the original beneath it, labelled with its language', async () => {
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_ESCALATION_CALL));
    mount(`/support/calls/${SAMPLE_ESCALATION_CALL.id}`);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const toggle = await screen.findByRole('switch', { name: 'English first' });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    expect(toggle).toBeChecked();

    const turn = within(log).getAllByTestId('turn-english')[0].closest('li')!;
    const lines = turn.querySelectorAll('p');
    expect(lines[0]).toHaveAttribute('data-testid', 'turn-english');
    expect(lines[0]).toHaveTextContent('When is my next EMI?');
    expect(lines[0]).not.toHaveTextContent('English:');
    expect(lines[0]).not.toHaveClass('muted');
    expect(lines[1]).toHaveTextContent(`Kannada: ${KANNADA_ASK}`);
    expect(lines[1]).toHaveClass('muted');
    expect(lines[1]).toHaveAttribute('lang', 'kn');
    expect(within(turn).getByText('Kannada')).toHaveClass('pill');

    fireEvent.click(toggle);
    expect(turn.querySelectorAll('p')[0]).toHaveTextContent(KANNADA_ASK);
  });

  it('shows no chip and a neutral label when a translation arrives without its language code', async () => {
    const call = structuredClone(SAMPLE_ESCALATION_CALL);
    const kn = call.turns.find((t) => t.text === KANNADA_ASK)!;
    delete kn.meta.language;
    h.getCall.mockResolvedValue(call);
    mount(`/support/calls/${call.id}`);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const turn = (await within(log).findByText(KANNADA_ASK)).closest('li')!;
    expect(turn.querySelector('.sc-lang')).toBeNull();
    expect(within(turn).getByTestId('turn-english')).toHaveTextContent('English: When is my next EMI?');

    fireEvent.click(screen.getByRole('switch', { name: 'English first' }));
    expect(turn.querySelectorAll('p')[1]).toHaveTextContent(`Original: ${KANNADA_ASK}`);
    expect(turn.querySelector('.sc-lang')).toBeNull();
  });

  it('offers no "English first" toggle when no turn has an English translation', async () => {
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_ROUTED_CALL));
    mount(`/support/calls/${SAMPLE_ROUTED_CALL.id}`);
    await screen.findByText('No speech detected');
    expect(screen.queryByRole('switch', { name: 'English first' })).toBeNull();
  });

  it('finds a turn by its English when searching', async () => {
    h.getCall.mockResolvedValue(structuredClone(SAMPLE_ESCALATION_CALL));
    mount(`/support/calls/${SAMPLE_ESCALATION_CALL.id}?q=EMI`);
    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const turn = (await within(log).findByText(KANNADA_ASK)).closest('li')!;
    expect(turn).toHaveAttribute('data-search', 'hit');
    expect(within(turn).getByText('EMI', { selector: 'mark' })).toBeInTheDocument();
    expect(within(log).getByText(ESCALATION_ASK, { selector: '.sc-turn.customer > p' }).closest('li')).toHaveAttribute('data-search', 'dim');
  });
});

describe('caller transcript corrections (Level 2 §6)', () => {
  const HEARD = 'No, I meant my vehicle loan, not the personal loan.';
  const CORRECTED = 'No, I meant my vehicle loan, not the personal loan, for account 2231.';

  /** The verified call with its second caller turn corrected by a reviewer; `seq` is that turn's position. */
  function corrected(): { call: SupportCallRecord; seq: number } {
    const call = structuredClone(SAMPLE_VERIFIED_CALL);
    const t = call.turns.find((x) => x.role === TurnRole.CUSTOMER && x.text === HEARD)!;
    t.meta.transcript_correction = { text: CORRECTED, author: 'reviewer', at: '2026-10-31T06:00:00Z' };
    return { call, seq: t.seq };
  }

  it('shows the corrected text as the turn and the recognised text beneath it as "Heard as"', async () => {
    const { call } = corrected();
    h.getCall.mockResolvedValue(call);
    mount(`/support/calls/${call.id}`);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const main = await within(log).findByText(CORRECTED);
    expect(main).not.toHaveClass('muted');
    const turn = main.closest('li')!;
    const heard = within(turn).getByTestId('turn-heard');
    expect(heard).toHaveTextContent(`Heard as: ${HEARD}`);
    expect(heard).toHaveClass('muted');
    expect(main.compareDocumentPosition(heard) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(turn).getByText(/Corrected by/)).toHaveTextContent(`Corrected by ${displayName('reviewer')}`);
    expect(screen.queryByRole('button', { name: 'Correct transcript' })).toBeNull();
  });

  it('keeps the English line and language chip of a translated caller turn under "Heard as"', async () => {
    const call = structuredClone(SAMPLE_ESCALATION_CALL);
    const KANNADA_ASK = 'ನನ್ನ ಮುಂದಿನ ಇಎಂಐ ಯಾವಾಗ?';
    const kn = call.turns.find((t) => t.text === KANNADA_ASK)!;
    kn.meta.transcript_correction = { text: 'ನನ್ನ ಮುಂದಿನ ಇಎಂಐ ಯಾವಾಗ ಬರುತ್ತದೆ?', author: 'reviewer', at: '2026-10-31T06:00:00Z' };
    h.getCall.mockResolvedValue(call);
    mount(`/support/calls/${call.id}`);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const turn = (await within(log).findByText('ನನ್ನ ಮುಂದಿನ ಇಎಂಐ ಯಾವಾಗ ಬರುತ್ತದೆ?')).closest('li')!;
    const lines = turn.querySelectorAll('p');
    expect(lines[0]).toHaveAttribute('lang', 'kn');
    expect(lines[1]).toHaveAttribute('data-testid', 'turn-heard');
    expect(lines[1]).toHaveTextContent(`Heard as: ${KANNADA_ASK}`);
    expect(lines[2]).toHaveAttribute('data-testid', 'turn-english');
    expect(lines[2]).toHaveTextContent('English: When is my next EMI?');
    expect(within(turn).getByText('Kannada')).toHaveClass('pill');
  });

  it('lets a reviewer correct a caller turn, prefilled with its current text, and remove a correction', async () => {
    const { call, seq } = corrected();
    h.getCall.mockResolvedValue(call);
    h.correctTranscript.mockResolvedValue({});
    h.clearTranscriptCorrection.mockResolvedValue({});
    mount(`/support/calls/${call.id}`, [Role.REVIEWER]);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const turn = (await within(log).findByText(CORRECTED)).closest('li')!;
    // Every caller turn gets the control; agent turns do not.
    const agentTurn = within(log).getAllByText('Agent')[0].closest('li')!;
    expect(within(agentTurn).queryByRole('button', { name: 'Correct transcript' })).toBeNull();

    fireEvent.click(within(turn).getByRole('button', { name: 'Correct transcript' }));
    const field = within(turn).getByLabelText('Corrected transcript') as HTMLInputElement;
    expect(field.value).toBe(CORRECTED);
    fireEvent.change(field, { target: { value: '  No, I meant my vehicle loan.  ' } });
    fireEvent.click(within(turn).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(h.correctTranscript).toHaveBeenCalledWith(call.id, seq, 'No, I meant my vehicle loan.'));
    await waitFor(() => expect(within(turn).queryByLabelText('Corrected transcript')).toBeNull());

    fireEvent.click(within(turn).getByRole('button', { name: 'Remove correction' }));
    await waitFor(() => expect(h.clearTranscriptCorrection).toHaveBeenCalledWith(call.id, seq));
  });

  it('prefills an uncorrected turn with the recognised text, Cancel closes the field, and a blank text cannot be saved', async () => {
    const call = structuredClone(SAMPLE_VERIFIED_CALL);
    h.getCall.mockResolvedValue(call);
    mount(`/support/calls/${call.id}`, [Role.ADMIN]);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const turn = (await within(log).findByText(HEARD)).closest('li')!;
    expect(within(turn).queryByRole('button', { name: 'Remove correction' })).toBeNull();
    fireEvent.click(within(turn).getByRole('button', { name: 'Correct transcript' }));
    const field = within(turn).getByLabelText('Corrected transcript') as HTMLInputElement;
    expect(field.value).toBe(HEARD);
    fireEvent.change(field, { target: { value: '   ' } });
    expect(within(turn).getByRole('button', { name: 'Save' })).toBeDisabled();
    fireEvent.click(within(turn).getByRole('button', { name: 'Cancel' }));
    expect(within(turn).queryByLabelText('Corrected transcript')).toBeNull();
    expect(h.correctTranscript).not.toHaveBeenCalled();
  });

  it('hides the control from an analyst but still shows the correction', async () => {
    const { call } = corrected();
    h.getCall.mockResolvedValue(call);
    mount(`/support/calls/${call.id}`, [Role.ANALYST]);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const turn = (await within(log).findByText(CORRECTED)).closest('li')!;
    expect(within(turn).getByTestId('turn-heard')).toHaveTextContent(`Heard as: ${HEARD}`);
    expect(screen.queryByRole('button', { name: 'Correct transcript' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Remove correction' })).toBeNull();
  });

  it('offers the control on a no-speech caller turn, and shows a correction saved on one', async () => {
    const call = structuredClone(SAMPLE_ROUTED_CALL);
    const silent = call.turns.find((t) => t.role === TurnRole.CUSTOMER && t.meta.no_speech)!;
    // Serve the call lazily and let a save land on it, as the core API would, so the page's refresh after saving sees it.
    h.getCall.mockImplementation(async () => structuredClone(call));
    h.correctTranscript.mockImplementation(async (_id: string, seq: number, text: string) => {
      const t = call.turns.find((x) => x.seq === seq)!;
      t.meta.transcript_correction = { text, author: 'reviewer', at: '2026-10-31T06:00:00Z' };
      return t;
    });
    mount(`/support/calls/${call.id}`, [Role.REVIEWER]);

    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const turn = (await within(log).findByText('No speech detected')).closest('li')!;
    fireEvent.click(within(turn).getByRole('button', { name: 'Correct transcript' }));
    const field = within(turn).getByLabelText('Corrected transcript') as HTMLInputElement;
    expect(field.value).toBe('');
    fireEvent.change(field, { target: { value: 'Hello, can you hear me?' } });
    fireEvent.click(within(turn).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(h.correctTranscript).toHaveBeenCalledWith(call.id, silent.seq, 'Hello, can you hear me?'));

    const main = await within(log).findByText('Hello, can you hear me?');
    const fixed = main.closest('li')!;
    expect(within(fixed).getByTestId('turn-heard')).toHaveTextContent('Heard as: (no speech detected)');
    expect(within(fixed).getByRole('button', { name: 'Remove correction' })).toBeInTheDocument();
  });

  it('finds a turn by its corrected text when searching', async () => {
    const { call } = corrected();
    h.getCall.mockResolvedValue(call);
    mount(`/support/calls/${call.id}?q=2231`);
    const log = await screen.findByRole('log', { name: 'Conversation history' });
    const turn = (await within(log).findByText(/for account/)).closest('li')!;
    expect(turn).toHaveAttribute('data-search', 'hit');
    expect(within(turn).getByText('2231', { selector: 'mark' })).toBeInTheDocument();
    expect(within(log).getByText('Can you send me the repayment schedule for it?').closest('li')).toHaveAttribute('data-search', 'dim');
  });
});
