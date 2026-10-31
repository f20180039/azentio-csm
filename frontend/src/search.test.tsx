import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Highlight, hitRanges, matches, normalise } from './search';

describe('matches', () => {
  it('matches everything on an empty or blank query', () => {
    expect(matches('', 'anything')).toBe(true);
    expect(matches('   ', null)).toBe(true);
  });

  it('is case-insensitive', () => {
    expect(matches('sr-40200', 'SR-40200')).toBe(true);
    expect(matches('REPAYMENT', 'repayment schedule')).toBe(true);
  });

  it('is accent-insensitive both ways', () => {
    expect(matches('jose', 'José Fernandes')).toBe(true);
    expect(matches('josé', 'Jose Fernandes')).toBe(true);
  });

  it('needs every term to match some field, in any order', () => {
    expect(matches('open repayment', 'REPAYMENT_SCHEDULE', 'OPEN')).toBe(true);
    expect(matches('open gold', 'REPAYMENT_SCHEDULE', 'OPEN')).toBe(false);
  });

  it('reads enum values as words', () => {
    expect(matches('ticket created', 'TICKET_CREATED')).toBe(true);
    expect(matches('ticket_created', 'Ticket created')).toBe(true);
    expect(normalise('SIM_AUDIO')).toBe('sim audio');
  });

  it('takes numbers, nested arrays and nulls', () => {
    expect(matches('42', 42)).toBe(true);
    expect(matches('loan', null, undefined, ['REPAYMENT', ['LOAN_APPLICATION']])).toBe(true);
    expect(matches('loan', null, [], undefined)).toBe(false);
  });
});

describe('Highlight', () => {
  it('wraps each match in a mark, keeping the original text', () => {
    const { container } = render(<Highlight text="Repayment schedule for VL-31003" query="schedule vl" />);
    expect(container.textContent).toBe('Repayment schedule for VL-31003');
    expect([...container.querySelectorAll('mark')].map((m) => m.textContent)).toEqual(['schedule', 'VL']);
  });

  it('maps accent-insensitive hits back onto the accented text', () => {
    expect(hitRanges('Café crème', 'creme')).toEqual([[5, 10]]);
  });

  it('merges overlapping hits and renders plain text with no query', () => {
    expect(hitRanges('ticket', 'tick cket')).toEqual([[0, 6]]);
    const { container } = render(<Highlight text="plain" query="" />);
    expect(container.querySelector('mark')).toBeNull();
  });
});
