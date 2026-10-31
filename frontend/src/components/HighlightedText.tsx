export interface Highlight {
  key: string;
  quote: string;
}

export interface Segment {
  text: string;
  keys: string[];
}

function quoteRegex(quote: string): RegExp | null {
  const tokens = quote.trim().split(/\s+/).filter(Boolean);
  if (!tokens.length) return null;
  const escaped = tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  return new RegExp(escaped.join('\\s+'), 'g');
}

/** Splits text into segments, tagging each with the highlight keys whose quote covers it. Whitespace-insensitive. */
export function segmentText(text: string, highlights: Highlight[]): Segment[] {
  const ranges: { start: number; end: number; key: string }[] = [];
  for (const h of highlights) {
    const re = quoteRegex(h.quote);
    if (!re) continue;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      ranges.push({ start: m.index, end: m.index + m[0].length, key: h.key });
      if (m[0].length === 0) re.lastIndex++;
    }
  }
  if (!ranges.length) return [{ text, keys: [] }];
  const cuts = new Set<number>([0, text.length]);
  ranges.forEach((r) => {
    cuts.add(r.start);
    cuts.add(r.end);
  });
  const points = [...cuts].sort((a, b) => a - b);
  const segments: Segment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [s, e] = [points[i], points[i + 1]];
    if (s === e) continue;
    const keys = ranges.filter((r) => r.start <= s && r.end >= e).map((r) => r.key);
    segments.push({ text: text.slice(s, e), keys });
  }
  return segments;
}

export function HighlightedText({
  text,
  highlights,
  activeKey,
  idPrefix,
}: {
  text: string;
  highlights: Highlight[];
  activeKey?: string | null;
  idPrefix: string;
}) {
  const segments = segmentText(text, highlights);
  const seen = new Set<string>();
  return (
    <pre className="doc-text">
      {segments.map((seg, i) => {
        if (!seg.keys.length) return <span key={i}>{seg.text}</span>;
        const firstNew = seg.keys.find((k) => !seen.has(k));
        seg.keys.forEach((k) => seen.add(k));
        return (
          <mark
            key={i}
            id={firstNew ? `${idPrefix}-${firstNew}` : undefined}
            data-keys={seg.keys.join(' ')}
            className={activeKey && seg.keys.includes(activeKey) ? 'active' : undefined}
          >
            {seg.text}
          </mark>
        );
      })}
    </pre>
  );
}
