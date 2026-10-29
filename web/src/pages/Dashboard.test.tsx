import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { sampleDashboard } from '../api/mock';
import type { Dashboard as DashboardData } from '../api/dashboard';
import { ToastProvider } from '../components/Toasts';

const getDashboard = vi.fn<() => Promise<DashboardData>>();
let failing = false; // a plain flag: vitest's spy leaves a derived promise unhandled when it records a rejection
vi.mock('../api/dashboard', () => ({
  getDashboard: () => (failing ? Promise.reject(new Error('down')) : getDashboard()),
}));

import { Dashboard } from './Dashboard';

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

function mount() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

const empty = (): DashboardData => ({
  ...sampleDashboard(),
  kpis: { ...sampleDashboard().kpis, callsToday: 0, callsTotal: 0, inProgress: 0, renewed: 0, handedOff: 0, saveRate: 0, premiumRetained: 0, blockedRequests: 0 },
  recentCalls: [],
  guardrailEvents: [],
});

beforeEach(() => {
  getDashboard.mockReset();
  failing = false;
});
afterEach(() => vi.useRealTimers());

describe('Dashboard', () => {
  it('renders the KPIs, outcome pills and feed from the sample data', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    mount();
    expect(await screen.findByText('Calls today')).toBeInTheDocument();
    const kpi = (name: string) => screen.getByText(name, { selector: '.kpi .label' }).closest('.kpi') as HTMLElement;
    expect(kpi('Calls today')).toHaveTextContent('7');
    expect(kpi('Save rate')).toHaveTextContent('67%');
    expect(kpi('Premium kept')).toHaveTextContent('₹1,84,500');
    expect(kpi('Blocked by rules')).toHaveTextContent('5');
    expect(kpi('Handed to a person')).toHaveTextContent('2');
    expect(screen.getAllByText('Renewed · payment pending', { selector: '.pill' })).toHaveLength(2);
    expect(screen.getByText('In progress', { selector: '.pill' })).toHaveClass('pulse');
    expect(screen.getByText('Asked for a discount the playbook does not allow')).toBeInTheDocument();
  });

  it('shows a designed empty state when there are no calls', async () => {
    getDashboard.mockResolvedValue(empty());
    mount();
    expect(await screen.findByText('No calls yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Renewals' })).toHaveAttribute('href', '/renewals');
    expect(screen.getByText(/run the simulated test/)).toBeInTheDocument();
  });

  it('opens the call from a table row and from a feed item', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    mount();
    fireEvent.click(await screen.findByText('Sample: Arjun Nair', { selector: 'td strong' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/renewals/calls/sample-2');
  });

  it('opens the call from a feed item', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    mount();
    fireEvent.click(await screen.findByRole('button', { name: /Date of birth did not match/ }));
    expect(screen.getByTestId('where')).toHaveTextContent('/renewals/calls/sample-3');
  });

  it('polls every 3 seconds and stops on unmount', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    getDashboard.mockResolvedValue(sampleDashboard());
    const { unmount } = mount();
    await act(async () => {});
    expect(getDashboard).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(getDashboard).toHaveBeenCalledTimes(2);
    unmount();
    await act(async () => {
      vi.advanceTimersByTime(12000);
    });
    expect(getDashboard).toHaveBeenCalledTimes(2);
  });

  it('keeps the last figures and does not reload on a failed poll', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    mount();
    await act(async () => {});
    failing = true;
    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByText('Calls today')).toBeInTheDocument();
    expect(screen.getByText(/Connection lost/)).toBeInTheDocument();
  });
});
