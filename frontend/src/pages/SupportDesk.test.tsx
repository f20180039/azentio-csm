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

  it('shows an error with Retry when the simulator is down', async () => {
    h.listRecords.mockRejectedValueOnce(new Error('Cannot reach the bank simulator'));
    mount();
    expect(await screen.findByText('Tickets could not be loaded')).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('SR-40200')).toBeInTheDocument();
  });
});
