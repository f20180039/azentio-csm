import { describe, expect, it } from 'vitest';
import { formatCallback } from './format';

describe('formatCallback', () => {
  const now = new Date(2026, 9, 29, 10, 0);
  const local = (d: number, h: number, m: number, y = 2026, mo = 9) => new Date(y, mo, d, h, m).toISOString();

  it('says Today for a time later today, in local time', () => {
    expect(formatCallback(local(29, 17, 0), now)).toBe('Today 17:00');
  });

  it('says Tomorrow for the next calendar day', () => {
    expect(formatCallback(local(30, 9, 30), now)).toBe('Tomorrow 09:30');
  });

  it('gives a date and time further out, with the year only when it differs', () => {
    expect(formatCallback(local(2, 17, 5, 2026, 10), now)).toBe('2 Nov, 17:05');
    expect(formatCallback(local(3, 8, 0, 2027, 0), now)).toBe('3 Jan 2027, 08:00');
  });

  it('falls back to the raw value when it is not a date', () => {
    expect(formatCallback('soon', now)).toBe('soon');
  });
});
