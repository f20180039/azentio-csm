import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { setFetcher } from '../api/client';
import { CaseStatus, type CaseSummary } from '../api/types';
import { ToastProvider } from '../components/Toasts';
import { matchesDate, Queue } from './Queue';

afterEach(() => setFetcher((...args) => fetch(...args)));

const mockCase = (overrides: Partial<CaseSummary> = {}): CaseSummary => ({
  id: 'case-1',
  caseType: 'renewal_call',
  title: 'Test Case 1',
  status: CaseStatus.NEEDS_REVIEW,
  riskScore: 60,
  amountAtRisk: 25000,
  findingsCount: 1,
  createdAt: new Date().toISOString(),
  ...overrides,
});

describe('matchesDate helper', () => {
  it('returns true when no filter is provided', () => {
    const c = mockCase();
    expect(matchesDate(c, '', '', '')).toBe(true);
  });

  it('matches today cases accurately', () => {
    const todayCase = mockCase({ createdAt: new Date().toISOString() });
    const oldCase = mockCase({ createdAt: '2020-01-01T12:00:00Z' });
    expect(matchesDate(todayCase, 'today', '', '')).toBe(true);
    expect(matchesDate(oldCase, 'today', '', '')).toBe(false);
  });

  it('matches yesterday cases accurately', () => {
    const yesterday = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    const yesterdayCase = mockCase({ createdAt: yesterday });
    const oldCase = mockCase({ createdAt: '2020-01-01T12:00:00Z' });
    expect(matchesDate(yesterdayCase, 'yesterday', '', '')).toBe(true);
    expect(matchesDate(oldCase, 'yesterday', '', '')).toBe(false);
  });

  it('matches 7d and 30d presets accurately', () => {
    const fourDaysAgo = new Date(Date.now() - 4 * 24 * 3600 * 1000).toISOString();
    const twentyDaysAgo = new Date(Date.now() - 20 * 24 * 3600 * 1000).toISOString();
    const oldCase = mockCase({ createdAt: '2020-01-01T12:00:00Z' });

    expect(matchesDate(mockCase({ createdAt: fourDaysAgo }), '7d', '', '')).toBe(true);
    expect(matchesDate(mockCase({ createdAt: twentyDaysAgo }), '7d', '', '')).toBe(false);

    expect(matchesDate(mockCase({ createdAt: twentyDaysAgo }), '30d', '', '')).toBe(true);
    expect(matchesDate(oldCase, '30d', '', '')).toBe(false);
  });

  it('matches custom date bounds accurately', () => {
    const target = mockCase({ createdAt: '2026-05-15T14:30:00Z' });
    expect(matchesDate(target, 'custom', '2026-05-01', '2026-05-31')).toBe(true);
    expect(matchesDate(target, 'custom', '2026-06-01', '2026-06-30')).toBe(false);
    expect(matchesDate(target, 'custom', '2026-05-16', '')).toBe(false);
  });
});

describe('Queue component date filtering', () => {
  it('renders review queue and filters by date', async () => {
    const today = new Date().toISOString();
    const past = '2022-01-01T10:00:00Z';
    const mockCases = [
      mockCase({ id: 'c-1', title: 'Recent Loan Case', createdAt: today }),
      mockCase({ id: 'c-2', title: 'Historic Policy Case', createdAt: past }),
    ];

    setFetcher(async (url) => {
      const u = String(url);
      if (u.includes('/cases')) {
        return new Response(JSON.stringify({ content: mockCases, totalElements: mockCases.length }), { status: 200 });
      }
      if (u.includes('/stats')) {
        return new Response(JSON.stringify({ jobsPending: 0, cacheHits: 1 }), { status: 200 });
      }
      if (u.includes('/packs')) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response('{}', { status: 200 });
    });

    render(
      <ToastProvider>
        <MemoryRouter initialEntries={['/queue?datePreset=today']}>
          <Queue />
        </MemoryRouter>
      </ToastProvider>,
    );

    expect(await screen.findByText('Recent Loan Case')).toBeInTheDocument();
    expect(screen.queryByText('Historic Policy Case')).not.toBeInTheDocument();

    // Clear filters button should be visible
    const clearBtn = screen.getByRole('button', { name: 'Clear filters' });
    expect(clearBtn).toBeInTheDocument();
    fireEvent.click(clearBtn);

    // After clearing, both cases appear
    expect(await screen.findByText('Historic Policy Case')).toBeInTheDocument();
  });
});
