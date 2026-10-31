import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mockSupport } from '../api/mockSupport';
import { ToastProvider } from '../components/Toasts';
import { SessionProvider } from '../session';
import { Role } from '../vocab';

const h = vi.hoisted(() => ({ setLessonStatus: vi.fn(), resolveReview: vi.fn() }));

vi.mock('../api/support', async (orig) => {
  const real = await orig<typeof import('../api/support')>();
  const { mockSupport: m } = await import('../api/mockSupport');
  return {
    ...real,
    getInsights: () => m.getInsights(),
    listReview: () => m.listReview(),
    listLessons: () => m.listLessons(),
    listRecords: (k: Parameters<typeof m.listRecords>[0]) => m.listRecords(k),
    getCall: (id: string) => m.getCall(id),
    setLessonStatus: h.setLessonStatus,
    resolveReview: h.resolveReview,
  };
});

import { SupportInsights } from './SupportInsights';

function mount(roles: Role[]) {
  return render(
    <ToastProvider>
      <SessionProvider initial={{ username: roles[0].toLowerCase(), password: 'x', roles }}>
        <MemoryRouter>
          <SupportInsights />
        </MemoryRouter>
      </SessionProvider>
    </ToastProvider>,
  );
}

const region = (name: string) => screen.getByRole('region', { name });

beforeEach(() => {
  h.setLessonStatus.mockReset().mockResolvedValue({});
  h.resolveReview.mockReset().mockResolvedValue({});
});

describe('SupportInsights', () => {
  it('renders the summary from stored data and the review reasons', async () => {
    mount([Role.ANALYST]);
    const insights = await mockSupport.getInsights();
    await waitFor(() => expect(screen.getByTestId('avg-rating')).toHaveTextContent(insights.ratings.average!.toFixed(1)));
    expect(within(region('Customer ratings')).getByRole('img', { name: /Ratings by score\. 5 ★: 1/ })).toBeInTheDocument();
    expect(within(region('Open reviews')).getByText(String(insights.openReviews))).toBeInTheDocument();
    expect(within(region('Active lessons')).getByText(String(insights.activeLessons))).toBeInTheDocument();

    const queue = screen.getByRole('region', { name: 'Review queue' });
    expect(await within(queue).findByText('Low rating')).toBeInTheDocument();
    expect(within(queue).getByText('Bad answer')).toBeInTheDocument();
    expect(within(queue).getByText('Dissatisfied')).toBeInTheDocument();
    expect(within(queue).queryByRole('button', { name: 'Mark reviewed' })).not.toBeInTheDocument();
    expect(within(queue).getByRole('button', { name: 'Export as test scenario' })).toBeInTheDocument();
  });

  it('gives an analyst no lesson actions', async () => {
    mount([Role.ANALYST]);
    const lessons = screen.getByRole('region', { name: 'Lessons' });
    expect(await within(lessons).findAllByText('Proposed')).toHaveLength(2);
    expect(within(lessons).queryByRole('button', { name: 'Activate' })).not.toBeInTheDocument();
    expect(within(lessons).queryByRole('button', { name: 'Propose a lesson' })).not.toBeInTheDocument();
  });

  it('lets a reviewer propose a lesson and mark a call reviewed, but not activate', async () => {
    mount([Role.REVIEWER]);
    const lessons = screen.getByRole('region', { name: 'Lessons' });
    await within(lessons).findAllByText('Proposed');
    expect(within(lessons).queryByRole('button', { name: 'Activate' })).not.toBeInTheDocument();
    fireEvent.click(within(lessons).getByRole('button', { name: 'Propose a lesson' }));
    expect(within(lessons).getByLabelText('Lesson text')).toBeInTheDocument();

    const queue = screen.getByRole('region', { name: 'Review queue' });
    fireEvent.click(await within(queue).findByRole('button', { name: 'Mark reviewed' }));
    fireEvent.change(within(queue).getByLabelText('Review note'), { target: { value: 'Needs a gold loan FAQ' } });
    fireEvent.click(within(queue).getByRole('button', { name: 'Mark reviewed' }));
    await waitFor(() => expect(h.resolveReview).toHaveBeenCalledWith('sample-call-routed', 'Needs a gold loan FAQ'));
  });

  it('lets an admin activate a proposed lesson and retire an active one', async () => {
    mount([Role.ADMIN]);
    const lessons = screen.getByRole('region', { name: 'Lessons' });
    const activate = await within(lessons).findAllByRole('button', { name: 'Activate' });
    expect(activate).toHaveLength(2);
    fireEvent.click(activate[0]);
    await waitFor(() => expect(h.setLessonStatus).toHaveBeenCalledWith('LSN-3', 'ACTIVE'));
    const row = within(lessons).getByText(/unauthorised card debit/).closest('tr')!;
    fireEvent.click(within(row).getByRole('button', { name: 'Retire' }));
    await waitFor(() => expect(h.setLessonStatus).toHaveBeenCalledWith('LSN-1', 'RETIRED'));
  });

  it('groups routed queries into FAQ gaps and exports a reviewed call as scenario YAML in a dialog', async () => {
    mount([Role.ADMIN]);
    const faq = screen.getByRole('region', { name: 'FAQ gaps' });
    expect(await within(faq).findByText('Can you book me a flight to Dubai?')).toBeInTheDocument();
    expect(within(faq).getAllByRole('button', { name: 'Copy as FAQ draft' }).length).toBeGreaterThanOrEqual(3);

    fireEvent.click(await screen.findByRole('button', { name: 'Export as test scenario' }));
    const dialog = await screen.findByRole('dialog', { name: 'Test scenario' });
    const yaml = (within(dialog).getByRole('textbox') as HTMLTextAreaElement).value;
    expect(yaml).toMatch(/^id: reviewed-sample-call-escalation/);
    expect(yaml).toContain('  - say: "There is a card payment of 48,999 rupees I never made."');
    expect(within(dialog).getByRole('button', { name: 'Copy' })).toBeInTheDocument();
  });
});
