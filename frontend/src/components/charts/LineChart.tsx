export interface LineSeries {
  key: string;
  label: string;
  /** A CSS color, e.g. 'var(--accent)' or '#8b5cf6' */
  color: string;
}

export interface LinePoint {
  label: string;
  values: Record<string, number>;
}

const W = 560;

function niceMax(v: number): number {
  if (v <= 4) return 4;
  const step = v <= 10 ? 2 : v <= 30 ? 4 : v <= 60 ? 10 : 20;
  return Math.ceil(v / step) * step;
}

/** Multi-series line chart with grid lines, data point markers, and accessible legend. */
export function LineChart({
  points,
  series,
  label,
  height = 190,
}: {
  points: LinePoint[];
  series: LineSeries[];
  label: string;
  height?: number;
}) {
  const allValues = points.flatMap((p) => series.map((s) => p.values[s.key] ?? 0));
  const max = niceMax(Math.max(1, ...allValues));

  const left = 32;
  const right = 20;
  const top = 18;
  const bottom = 26;
  const H = height;
  const pw = W - left - right;
  const ph = H - top - bottom;

  const ticks = [0, Math.round(max / 2), max];
  const x = (i: number) => (points.length <= 1 ? left + pw / 2 : left + (i / (points.length - 1)) * pw);
  const y = (v: number) => top + ph - (Math.min(v, max) / max) * ph;

  const summary = `${label}. Points: ${points.map((p) => `${p.label} (${series.map((s) => `${s.label}: ${p.values[s.key] ?? 0}`).join(', ')})`).join('; ')}.`;

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} className="chart-svg">
        {/* Horizontal grid lines & Y-ticks */}
        {ticks.map((t) => {
          const yPos = y(t);
          return (
            <g key={t}>
              <line x1={left} x2={W - right} y1={yPos} y2={yPos} className="chart-grid" />
              <text x={left - 6} y={yPos + 4} textAnchor="end" className="chart-tick">
                {t}
              </text>
            </g>
          );
        })}

        {/* X-axis baseline */}
        <line x1={left} x2={W - right} y1={top + ph} y2={top + ph} className="chart-axis" />

        {/* X-axis labels */}
        {points.map((pt, i) => (
          <text key={pt.label} x={x(i)} y={H - 8} textAnchor="middle" className="chart-label">
            {pt.label}
          </text>
        ))}

        {/* Line Series */}
        {series.map((s) => {
          const coords = points.map((p, i) => ({
            x: x(i),
            y: y(p.values[s.key] ?? 0),
            val: p.values[s.key] ?? 0,
            pointLabel: p.label,
          }));

          const polylinePts = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');

          return (
            <g key={s.key} className="line-series" data-series={s.key}>
              <polyline
                points={polylinePts}
                fill="none"
                stroke={s.color}
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {coords.map((c, i) => (
                <circle
                  key={i}
                  cx={c.x}
                  cy={c.y}
                  r="3.5"
                  fill={s.color}
                  stroke="var(--surface)"
                  strokeWidth="1.5"
                >
                  <title>{`${s.label} (${c.pointLabel}): ${c.val}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
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
