import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LineChart, type LinePoint, type LineSeries } from './LineChart';

const series: LineSeries[] = [
  { key: 'repayment', label: 'Repayment', color: 'rgb(41, 196, 131)' },
  { key: 'complaint', label: 'Complaint', color: 'rgb(179, 38, 30)' },
];

const points: LinePoint[] = [
  { label: 'Mon', values: { repayment: 12, complaint: 2 } },
  { label: 'Tue', values: { repayment: 15, complaint: 4 } },
  { label: 'Wed', values: { repayment: 8, complaint: 1 } },
];

function texts(container: HTMLElement, cls: string) {
  return [...container.querySelectorAll(`text.${cls}`)];
}

describe('LineChart', () => {
  it('renders a polyline for each series and points within the viewBox', () => {
    const { container } = render(<LineChart points={points} series={series} label="Test chart" />);
    const svg = container.querySelector('svg');
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute('role', 'img');
    expect(svg?.getAttribute('aria-label')).toContain('Test chart');

    const polylines = container.querySelectorAll('polyline');
    expect(polylines).toHaveLength(series.length);

    const circles = container.querySelectorAll('circle');
    expect(circles).toHaveLength(points.length * series.length);
  });

  it('uses whole-number axis ticks and renders X-axis labels', () => {
    const { container } = render(<LineChart points={points} series={series} label="Intent trends" />);
    const ticks = texts(container, 'chart-tick');
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    for (const t of ticks) {
      expect(Number.isInteger(Number(t.textContent))).toBe(true);
    }

    const labels = texts(container, 'chart-label');
    expect(labels.map((l) => l.textContent)).toEqual(['Mon', 'Tue', 'Wed']);
  });

  it('renders a legend with matching labels and color indicators', () => {
    const { container } = render(<LineChart points={points} series={series} label="Test legend" />);
    const legend = container.querySelector('.chart-legend');
    expect(legend).toBeInTheDocument();
    expect(legend).toHaveTextContent('Repayment');
    expect(legend).toHaveTextContent('Complaint');
  });
});
