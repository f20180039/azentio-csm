import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCredentials, setFetcher } from '../api/client';
import { SAMPLE_ESCALATION_CALL, SAMPLE_ROUTED_CALL } from '../api/mockSupport';
import type { SupportCall as SupportCallRecord } from '../api/support';
import { ToastProvider } from '../components/Toasts';
import { SessionProvider } from '../session';
import { Role } from '../vocab';
import { SupportCall } from './SupportCall';

type Sent = { method: string; url: string; body: unknown };

/** Serves the call over the real API client and records every write. */
function serve(call: SupportCallRecord): Sent[] {
  const sent: Sent[] = [];
  setFetcher(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method === 'GET') return new Response(JSON.stringify(call), { status: 200 });
    sent.push({ method, url, body: JSON.parse(String(init?.body)) });
    return new Response(JSON.stringify({}), { status: 201 });
  });
  return sent;
}

function mount(call: SupportCallRecord, roles: Role[]) {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  return render(
    <ToastProvider>
      <SessionProvider initial={{ username: roles[0].toLowerCase(), password: 'x', roles }}>
        <MemoryRouter initialEntries={[`/support/calls/${call.id}`]}>
          <Routes>
            <Route path="/support/calls/:callId" element={<SupportCall />} />
          </Routes>
        </MemoryRouter>
      </SessionProvider>
    </ToastProvider>,
  );
}

afterEach(() => {
  setFetcher((...a) => fetch(...a));
  setCredentials(null);
});

describe('SupportCall ratings and feedback', () => {
  it('posts a PANEL rating with the chosen stars and comment when an ended call has none', async () => {
    const sent = serve(structuredClone(SAMPLE_ESCALATION_CALL));
    mount(SAMPLE_ESCALATION_CALL, [Role.ANALYST]);
    const panel = await screen.findByRole('region', { name: 'Customer rating' });
    const save = within(panel).getByRole('button', { name: 'Save rating' });
    expect(save).toBeDisabled();
    fireEvent.click(within(panel).getByRole('radio', { name: '4 stars' }));
    fireEvent.change(within(panel).getByLabelText('Rating comment (optional)'), { target: { value: 'Handled the fraud report well' } });
    fireEvent.click(save);
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].method).toBe('POST');
    expect(sent[0].url).toMatch(/\/support\/calls\/sample-call-escalation\/rating$/);
    expect(sent[0].body).toEqual({ score: 4, comment: 'Handled the fraud report well', source: 'PANEL' });
  });

  it('shows an existing rating with its source', async () => {
    serve(structuredClone(SAMPLE_ROUTED_CALL));
    mount(SAMPLE_ROUTED_CALL, [Role.ANALYST]);
    const panel = await screen.findByRole('region', { name: 'Customer rating' });
    expect(within(panel).getByRole('img', { name: '2 out of 5 stars' })).toBeInTheDocument();
    expect(within(panel).getByText(/Rated by the customer on the call/)).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Save rating' })).not.toBeInTheDocument();
  });

  it('hides feedback buttons from an analyst but shows existing feedback', async () => {
    serve(structuredClone(SAMPLE_ROUTED_CALL));
    mount(SAMPLE_ROUTED_CALL, [Role.ANALYST]);
    expect(await screen.findByText('👎 Bad answer')).toBeInTheDocument();
    expect(screen.getByText(/Say that live gold prices/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Good answer' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Bad answer' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Propose a lesson' })).not.toBeInTheDocument();
  });

  it('lets a reviewer post a BAD verdict with a correction, and a GOOD verdict', async () => {
    const sent = serve(structuredClone(SAMPLE_ROUTED_CALL));
    mount(SAMPLE_ROUTED_CALL, [Role.REVIEWER]);
    fireEvent.click(await screen.findByRole('button', { name: 'Bad answer' }));
    fireEvent.change(screen.getByLabelText('What should it have said?'), { target: { value: 'Offer the gold loan FAQ first.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save feedback' }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].url).toMatch(/\/support\/calls\/sample-call-routed\/turns\/3\/feedback$/);
    expect(sent[0].body).toEqual({ verdict: 'BAD', correction: 'Offer the gold loan FAQ first.' });

    fireEvent.click(screen.getByRole('button', { name: 'Good answer' }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].body).toEqual({ verdict: 'GOOD', correction: null });
  });

  it('lets a reviewer propose a lesson prefilled from the correction', async () => {
    const sent = serve(structuredClone(SAMPLE_ROUTED_CALL));
    mount(SAMPLE_ROUTED_CALL, [Role.REVIEWER]);
    fireEvent.click(await screen.findByRole('button', { name: 'Propose a lesson' }));
    const text = screen.getByLabelText('Lesson text') as HTMLTextAreaElement;
    expect(text.value).toMatch(/^Say that live gold prices/);
    fireEvent.click(screen.getByRole('button', { name: 'Propose lesson' }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].url).toMatch(/\/support\/lessons$/);
    expect(sent[0].body).toEqual({ text: text.value.trim(), sourceCallId: 'sample-call-routed', sourceSeq: 3 });
  });
});
