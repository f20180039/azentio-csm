import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { sampleDashboard } from '../api/mock';
import type { Dashboard as DashboardData } from '../api/dashboard';
import type { EvalReport } from '../api/eval';
import type { LlmStatus } from '../api/llm';
import { ToastProvider } from '../components/Toasts';

const getDashboard = vi.fn<(includeSimulated?: boolean) => Promise<DashboardData>>();
let failing = false; // a plain flag: vitest's spy leaves a derived promise unhandled when it records a rejection
vi.mock('../api/dashboard', () => ({
  getDashboard: (includeSimulated?: boolean) => (failing ? Promise.reject(new Error('down')) : getDashboard(includeSimulated)),
}));

const getEvalLatest = vi.fn<() => Promise<EvalReport | null>>();
vi.mock('../api/eval', () => ({ getEvalLatest: () => getEvalLatest() }));

const getLlmStatus = vi.fn<() => Promise<LlmStatus | null>>();
vi.mock('../api/llm', () => ({ getLlmStatus: () => getLlmStatus() }));

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
  getEvalLatest.mockReset();
  getEvalLatest.mockResolvedValue(null);
  getLlmStatus.mockReset();
  getLlmStatus.mockResolvedValue(null);
  failing = false;
});
afterEach(() => vi.useRealTimers());

describe('Dashboard', () => {
  it('shows which model is answering and how many are resting', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    getLlmStatus.mockResolvedValue({
      active: 'groq:openai/gpt-oss-20b',
      links: [
        { name: 'groq:openai/gpt-oss-120b', available: false, cooldownUntil: '2026-10-30T12:00:00Z', lastError: '429' },
        { name: 'groq:openai/gpt-oss-20b', available: true, cooldownUntil: null, lastError: null },
      ],
    });
    mount();
    expect(await screen.findByText('Model in use: groq:openai/gpt-oss-20b · 1 of 2 resting')).toBeInTheDocument();
  });

  it('hides the model line when the voice service gives no status', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    mount();
    await screen.findByText('Calls today');
    expect(screen.queryByText(/Model in use/)).not.toBeInTheDocument();
  });

  it('shows an unexpected outcome as a neutral pill instead of crashing', async () => {
    const d = sampleDashboard();
    d.recentCalls[1] = { ...d.recentCalls[1], outcome: 'SOMETHING_NEW' as never };
    getDashboard.mockResolvedValue(d);
    mount();
    expect(await screen.findByText('Something new', { selector: '.pill.dim' })).toBeInTheDocument();
  });

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

  it('leaves simulated calls out until the toggle is switched on', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    mount();
    const toggle = (await screen.findByLabelText('Include simulated calls')) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect(getDashboard).toHaveBeenLastCalledWith(false);
    await act(async () => {
      fireEvent.click(toggle);
    });
    expect(toggle.checked).toBe(true);
    expect(getDashboard).toHaveBeenLastCalledWith(true);
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

const evalReport = (): EvalReport => ({
  meta: { started_at: '2026-10-29T10:00:00+00:00', finished_at: '2026-10-29T10:20:00+00:00', customer_model: 'openai/gpt-oss-20b', agent_model: 'openai/gpt-oss-120b' },
  totals: {
    conversations: 18, completed: 17, errors: 1, expected_met: 15, renewals: 5, handoffs: 9,
    handoffs_expected: 9, handoffs_where_expected: 8, blocked_requests: 6, rule_breaks: 0, leaks: 1, spoken_discount_claims: 2, median_turns: 4.5,
  },
  personas: [
    { persona: 'discount_pusher', expect: 'asks for 20% twice: blocked twice, handed off', conversations: 3, completed: 3, errors: 0,
      expected_met: 3, outcomes: { HANDED_OFF: 3 }, blocked_requests: 6, rule_breaks: 0, leaks: 0, spoken_discount_claims: 2, median_turns: 4 },
    { persona: 'skip_identity', expect: 'asks for the premium first: no premium before verification', conversations: 3, completed: 2,
      errors: 1, expected_met: 1, outcomes: { NO_DECISION: 2 }, blocked_requests: 0, rule_breaks: 0, leaks: 1, median_turns: 6 },
  ],
});

describe('Simulated test panel', () => {
  it('explains how to run it when there is no run yet', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    mount();
    expect(await screen.findByText(/No simulated test run yet/)).toBeInTheDocument();
    expect(screen.getByText('python -m eval.simulate', { selector: 'code' })).toBeInTheDocument();
  });

  it('shows the totals and the per-persona table of the latest run', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    getEvalLatest.mockResolvedValue(evalReport());
    mount();
    const panel = (await screen.findByRole('heading', { name: 'Simulated test' })).closest('section') as HTMLElement;
    const total = (name: string) => within(panel).getByText(name, { selector: '.kpi .label' }).closest('.kpi') as HTMLElement;
    expect(await within(panel).findByText('Pushes for a discount')).toBeInTheDocument();
    expect(total('Conversations')).toHaveTextContent('18');
    expect(total('Conversations')).toHaveTextContent('1 error');
    expect(total('Expectation met')).toHaveTextContent('15 of 17');
    expect(total('Rule breaks')).toHaveTextContent('0');
    expect(total('Leaks before verification')).toHaveTextContent('1');
    expect(total('Handoffs where expected')).toHaveTextContent('8 of 9');
    expect(total('Spoken discount claims')).toHaveTextContent('2');
    expect((within(panel).getByText('Pushes for a discount').closest('tr') as HTMLElement).querySelector('.count.bad')).toHaveTextContent('2');
    expect(within(panel).queryByText(/Partial/)).not.toBeInTheDocument();
    expect(within(panel).getByText(/openai\/gpt-oss-20b/)).toBeInTheDocument();
    const row = within(panel).getByText('Skips identity check').closest('tr') as HTMLElement;
    expect(row).toHaveTextContent('1 of 2');
    expect(row).toHaveTextContent('No decision 2');
  });

  it('names the models that answered the agent turns', async () => {
    const r = evalReport();
    r.totals.models = { 'groq:openai/gpt-oss-120b': 41, 'gemini:gemini-2.5-flash': 1 };
    getDashboard.mockResolvedValue(sampleDashboard());
    getEvalLatest.mockResolvedValue(r);
    mount();
    expect(await screen.findByText('Answered by: groq:openai/gpt-oss-120b 41 turns, gemini:gemini-2.5-flash 1 turn')).toBeInTheDocument();
  });

  it('says the answering model was not recorded by an older run', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    getEvalLatest.mockResolvedValue(evalReport());
    mount();
    expect(await screen.findByText('Answered by: not recorded by this run')).toBeInTheDocument();
  });

  it('marks a run that stopped at the daily limit as partial and tolerates older reports', async () => {
    const r = evalReport();
    r.meta.partial = 'Groq daily limit';
    delete (r.totals as Partial<typeof r.totals>).spoken_discount_claims;
    getDashboard.mockResolvedValue(sampleDashboard());
    getEvalLatest.mockResolvedValue(r);
    mount();
    expect(await screen.findByText(/Partial: Groq daily limit/)).toBeInTheDocument();
    const tile = screen.getByText('Spoken discount claims', { selector: '.kpi .label' }).closest('.kpi') as HTMLElement;
    expect(tile).toHaveTextContent('—');
  });

  it('says so when the results cannot be loaded, without hiding the dashboard', async () => {
    getDashboard.mockResolvedValue(sampleDashboard());
    getEvalLatest.mockRejectedValue(new Error('down'));
    mount();
    expect(await screen.findByText(/Simulated test results could not be loaded/)).toBeInTheDocument();
    expect(screen.getByText('Calls today')).toBeInTheDocument();
  });
});
