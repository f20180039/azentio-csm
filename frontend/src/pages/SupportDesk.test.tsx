import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SAMPLE_RECORDS, SAMPLE_ROUTED_CALL, SAMPLE_VERIFIED_CALL } from '../api/mockSupport';
import type { RecordKind, SupportCallSummary } from '../api/support';
import { SupportDesk } from './SupportDesk';

const h = vi.hoisted(() => ({ listCalls: vi.fn(), listRecords: vi.fn() }));

vi.mock('../api/support', async (orig) => {
  const real = await orig<typeof import('../api/support')>();
  return { ...real, listCalls: h.listCalls, listRecords: h.listRecords };
});

const summary = (c: typeof SAMPLE_VERIFIED_CALL): SupportCallSummary => ({
  id: c.id, channel: c.channel, startedAt: c.startedAt, endedAt: c.endedAt, outcome: c.outcome, verified: c.verified,
  turnCount: c.turns.length, intents: [...new Set(c.turns.flatMap((t) => t.meta.intents ?? []))],
});

beforeEach(() => {
  h.listCalls.mockReset().mockResolvedValue([summary(SAMPLE_VERIFIED_CALL), summary(SAMPLE_ROUTED_CALL)]);
  h.listRecords.mockReset().mockImplementation(async (kind: RecordKind) => SAMPLE_RECORDS[kind]);
});

function mount() {
  return render(
    <MemoryRouter>
      <SupportDesk />
    </MemoryRouter>,
  );
}

describe('SupportDesk', () => {
  it('renders each records tab from listRecords', async () => {
    mount();
    const tabs = screen.getByRole('tablist', { name: 'Record type' });
    expect(within(tabs).getAllByRole('tab').map((t) => t.textContent)).toEqual(['Tickets', 'Complaints', 'Routed queries', 'Escalations']);

    const panel = () => screen.getByRole('tabpanel');
    expect(await within(panel()).findByText('SR-40200')).toBeInTheDocument();
    expect(within(panel()).getByText('Repayment schedule')).toHaveAttribute('title', 'REPAYMENT_SCHEDULE');
    expect(h.listRecords).toHaveBeenCalledWith('ticket');

    fireEvent.click(screen.getByRole('tab', { name: 'Complaints' }));
    expect(await within(panel()).findByText('CMP-50200')).toBeInTheDocument();
    expect(within(panel()).getByText('Escalated')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Routed queries' }));
    expect(await within(panel()).findByText('RQ-60200')).toBeInTheDocument();
    expect(within(panel()).getByText(/gold rate in Mumbai/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'Escalations' }));
    expect(await within(panel()).findByText('ESC-70200')).toBeInTheDocument();
    expect(h.listRecords.mock.calls.map((c) => c[0])).toEqual(expect.arrayContaining(['ticket', 'complaint', 'routed', 'escalation']));
  });

  it('lists calls and filters them by outcome', async () => {
    mount();
    expect(await screen.findAllByText('Ticket created')).not.toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Routed' }));
    await waitFor(() => expect(h.listCalls).toHaveBeenLastCalledWith('ROUTED'));
    expect(screen.getByRole('button', { name: 'Routed' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('searches the tickets tab by reference, highlights the hit and counts every tab', async () => {
    mount();
    const panel = () => screen.getByRole('tabpanel');
    expect(await within(panel()).findByText('SR-40102')).toBeInTheDocument();

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search bank records' }), { target: { value: 'SR-40200' } });
    await waitFor(() => expect(within(panel()).getAllByRole('row')).toHaveLength(2));
    const hit = within(panel()).getByText('SR-40200');
    expect(hit.tagName).toBe('MARK');
    expect(within(panel()).queryByText('SR-40102')).not.toBeInTheDocument();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Complaints 0' })).toBeInTheDocument());
    expect(screen.getByRole('tab', { name: 'Tickets 1' })).toBeInTheDocument();

    fireEvent.change(screen.getByRole('searchbox', { name: 'Search bank records' }), { target: { value: 'xyz' } });
    expect(await screen.findByText('No results for ‘xyz’')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    await waitFor(() => expect(within(panel()).getByText('SR-40102')).toBeInTheDocument());
  });

  it('searches calls by intent label', async () => {
    mount();
    expect(await screen.findAllByText('Ticket created')).not.toHaveLength(0);
    const callsTable = () => screen.getAllByRole('table')[0];
    const before = within(callsTable()).getAllByRole('row').length;
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search calls' }), { target: { value: 'ticket created' } });
    await waitFor(() => expect(within(callsTable()).getAllByRole('row').length).toBeLessThan(before));
    expect(screen.getByText(`1 of ${before - 1}`)).toBeInTheDocument();
  });

  it('shows a phone call as Phone and finds it by that channel', async () => {
    h.listCalls.mockResolvedValue([summary(SAMPLE_VERIFIED_CALL), { ...summary(SAMPLE_ROUTED_CALL), channel: 'PHONE' }]);
    mount();
    const callsTable = () => screen.getAllByRole('table')[0];
    expect(await within(callsTable()).findByText('Phone')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search calls' }), { target: { value: 'ticket created' } });
    await waitFor(() => expect(within(callsTable()).queryByText('Phone')).not.toBeInTheDocument());
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search calls' }), { target: { value: 'phone' } });
    expect(await within(callsTable()).findByText('Phone')).toBeInTheDocument();
  });

  it('shows an error with Retry when the simulator is down', async () => {
    h.listRecords.mockRejectedValueOnce(new Error('Cannot reach the bank simulator'));
    mount();
    expect(await screen.findByText('Tickets could not be loaded')).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('SR-40200')).toBeInTheDocument();
  });
});
