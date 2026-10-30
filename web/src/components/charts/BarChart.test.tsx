import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BarChart } from './BarChart';

const series = [{ key: 'a', label: 'A', color: 'red' }];
const rows = [{ label: 'x', values: { a: 15 } }, { label: 'y', values: { a: 3 } }];

function texts(container: HTMLElement, cls: string) {
  return [...container.querySelectorAll(`text.${cls}`)];
}

describe('BarChart', () => {
  it.each([false, true])('keeps the total label of a full-length bar inside the viewBox (horizontal=%s)', (horizontal) => {
    const { container } = render(<BarChart rows={rows} series={series} label="t" horizontal={horizontal} />);
    const [, , w, h] = container.querySelector('svg')!.getAttribute('viewBox')!.split(' ').map(Number);
    const label = texts(container, 'chart-value').find((t) => t.textContent === '15')!;
    expect(Number(label.getAttribute('y'))).toBeGreaterThanOrEqual(11);
    expect(Number(label.getAttribute('y'))).toBeLessThanOrEqual(h);
    expect(Number(label.getAttribute('x')) + (horizontal ? 16 : 8)).toBeLessThanOrEqual(w);
  });

  it('uses whole-number axis ticks', () => {
    const { container } = render(<BarChart rows={rows} series={series} label="t" />);
    for (const t of texts(container, 'chart-tick')) expect(Number.isInteger(Number(t.textContent))).toBe(true);
  });
});
