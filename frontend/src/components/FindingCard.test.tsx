import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Finding } from '../api/types';
import { FindingCard } from './FindingCard';
import { segmentText } from './HighlightedText';
import { ToastProvider } from './Toasts';

const finding: Finding = {
  id: 'f-1',
  ruleId: 'BS-BALANCE-CHAIN',
  title: 'Balance chain breaks',
  detail: 'Expected 1,03,606.40',
  severity: 'HIGH',
  weight: 0.7,
  amount: 10000,
  source: 'RULE',
  evidence: [{ documentId: 'd1', page: 2, quote: 'ACH CR SALARY' }],
  llmNote: 'Only the 30-Sep row is inflated.',
  verified: true,
  status: 'OPEN',
};

function renderCard(canDecide: boolean, onShowEvidence = vi.fn()) {
  render(
    <ToastProvider>
      <FindingCard caseId="c1" finding={finding} canDecide={canDecide} onDecided={vi.fn()} onShowEvidence={onShowEvidence} />
    </ToastProvider>,
  );
  return onShowEvidence;
}

describe('FindingCard', () => {
  it('shows rule, weight, verified badge and decision buttons for a reviewer', () => {
    renderCard(true);
    expect(screen.getByText('Balance chain breaks')).toBeInTheDocument();
    expect(screen.getByText('BS-BALANCE-CHAIN')).toBeInTheDocument();
    expect(screen.getByText('0.70')).toBeInTheDocument();
    expect(screen.getByText('Quote verified')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept' })).toBeInTheDocument();
  });

  it('hides decision buttons from an analyst', () => {
    renderCard(false);
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull();
    expect(screen.getByText('Only reviewers can decide findings.')).toBeInTheDocument();
  });

  it('requires a reason before dismissing', () => {
    renderCard(true);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.getByRole('button', { name: 'Dismiss finding' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Reason (required)'), { target: { value: 'Refund from same merchant' } });
    expect(screen.getByRole('button', { name: 'Dismiss finding' })).toBeEnabled();
  });

  it('jumps to evidence with the document id', () => {
    const onShow = renderCard(false);
    fireEvent.click(screen.getByRole('button', { name: /Evidence 1/ }));
    expect(onShow).toHaveBeenCalledWith('f-1-e0', 'd1');
  });
});

describe('segmentText', () => {
  it('matches quotes regardless of whitespace', () => {
    const segs = segmentText('a  ACH CR\nSALARY b', [{ key: 'k', quote: 'ACH CR SALARY' }]);
    expect(segs.find((s) => s.keys.includes('k'))?.text).toBe('ACH CR\nSALARY');
  });
});
