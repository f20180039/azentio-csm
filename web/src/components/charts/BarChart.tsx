export interface BarSeries {
  key: string;
  label: string;
  /** A CSS colour, normally a theme token such as var(--ok). */
  color: string;
}

export interface BarRow {
  label: string;
  values: Record<string, number>;
}

const W = 360;

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const step = v <= 10 ? 2 : v <= 30 ? 4 : v <= 60 ? 10 : 20; // even, so the midpoint tick is a whole number
  return Math.ceil(v / step) * step;
}

/** Stacked bars drawn to scale. Vertical = one column per row; horizontal = one bar per row. */
export function BarChart({
  rows,
  series,
  label,
  horizontal = false,
}: {
  rows: BarRow[];
  series: BarSeries[];
  label: string;
  horizontal?: boolean;
}) {
  const totals = rows.map((r) => series.reduce((s, x) => s + (r.values[x.key] ?? 0), 0));
  const max = niceMax(Math.max(0, ...totals));
  const summary = `${label}. ${rows
    .map((r, i) => `${r.label}: ${totals[i]} (${series.map((s) => `${r.values[s.key] ?? 0} ${s.label.toLowerCase()}`).join(', ')})`)
    .join('; ')}.`;

  const left = horizontal ? 64 : 28;
  const right = horizontal ? 26 : 8;
  const top = 18;
  const bottom = horizontal ? 22 : 24;
  const H = horizontal ? top + bottom + rows.length * 34 : 170;
  const pw = W - left - right;
  const ph = H - top - bottom;
  const ticks = [0, max / 2, max];

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} className="chart-svg">
        {ticks.map((t) => {
          const p = (t / max) * (horizontal ? pw : ph);
          return horizontal ? (
            <g key={t}>
              <line x1={left + p} x2={left + p} y1={top} y2={top + ph} className="chart-grid" />
              <text x={left + p} y={H - 8} textAnchor="middle" className="chart-tick">{t}</text>
            </g>
          ) : (
            <g key={t}>
              <line x1={left} x2={W - right} y1={top + ph - p} y2={top + ph - p} className="chart-grid" />
              <text x={left - 6} y={top + ph - p + 4} textAnchor="end" className="chart-tick">{t}</text>
            </g>
          );
        })}
        {rows.map((r, i) => {
          let acc = 0;
          const slot = (horizontal ? ph : pw) / rows.length;
          const thick = Math.min(horizontal ? 18 : 28, slot * 0.62);
          const pos = (horizontal ? top : left) + slot * i + (slot - thick) / 2;
          return (
            <g key={r.label}>
              <title>{`${r.label}: ${totals[i]}`}</title>
              {series.map((s) => {
                const v = r.values[s.key] ?? 0;
                if (v <= 0) return null;
                const len = (v / max) * (horizontal ? pw : ph);
                const rect = horizontal ? (
                  <rect key={s.key} x={left + acc} y={pos} width={len} height={thick} fill={s.color} />
                ) : (
                  <rect key={s.key} x={pos} y={top + ph - acc - len} width={thick} height={len} fill={s.color} />
                );
                acc += len;
                return rect;
              })}
              {horizontal ? (
                <>
                  <text x={left - 8} y={pos + thick / 2 + 4} textAnchor="end" className="chart-label">{r.label}</text>
                  {totals[i] > 0 && <text x={left + acc + 6} y={pos + thick / 2 + 4} className="chart-value">{totals[i]}</text>}
                </>
              ) : (
                <>
                  <text x={pos + thick / 2} y={H - 8} textAnchor="middle" className="chart-label">{r.label}</text>
                  {totals[i] > 0 && <text x={pos + thick / 2} y={top + ph - acc - 4} textAnchor="middle" className="chart-value">{totals[i]}</text>}
                </>
              )}
            </g>
          );
        })}
        <line
          x1={left} x2={horizontal ? left : W - right} y1={top + ph} y2={horizontal ? top : top + ph}
          className="chart-axis"
        />
      </svg>
      <figcaption className="chart-legend">
        {series.map((s) => (
          <span key={s.key}>
            <i style={{ background: s.color }} aria-hidden="true" />
            {s.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
