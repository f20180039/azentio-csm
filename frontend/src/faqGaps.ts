import type { OpsRecord } from './api/support';

export interface FaqGap {
  /** The shared key words, most common first. */
  keywords: string[];
  count: number;
  /** Distinct wordings, most frequent first, at most MAX_EXAMPLES. */
  examples: string[];
  refs: string[];
  callIds: string[];
}

const MAX_EXAMPLES = 3;

const STOPWORDS = new Set(
  ('a an and any are at be can could do does for from give have how i im in is it me my of on or please some ' +
    'tell that the this to today want what whats when where which who why will with would you your should ' +
    'week need know about there their get')
    .split(' '),
);

/** Routed summaries are "<query> — <reason>"; keep the customer's words only. */
export function queryText(summary: string): string {
  return summary.split(/\s+[—–|]\s+|\s+-\s+/)[0].trim();
}

/** Lower case, punctuation removed, whitespace collapsed. */
export function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function stem(word: string): string {
  if (word.length > 4 && word.endsWith('ies')) return word.slice(0, -3) + 'y';
  if (word.length > 3 && word.endsWith('s') && !word.endsWith('ss')) return word.slice(0, -1);
  return word;
}

export function keywords(text: string): string[] {
  return [...new Set(normalise(text).split(' ').filter((w) => w && !STOPWORDS.has(w) && !/^\d+$/.test(w)).map(stem))];
}

/** Two wordings are similar when they share two key words, or half the key words of the shorter one. */
function similar(a: string[], b: string[]): boolean {
  const shared = a.filter((w) => b.includes(w)).length;
  return shared >= 2 || (shared >= 1 && shared / Math.min(a.length, b.length) >= 0.5);
}

/** Groups routed queries by similar wording, biggest group first. */
export function groupFaqGaps(records: Pick<OpsRecord, 'summary' | 'ref' | 'call_id'>[]): FaqGap[] {
  type Group = { members: { text: string; words: string[]; ref: string; callId: string | null }[] };
  const groups: Group[] = [];
  for (const r of records) {
    const text = queryText(r.summary);
    const words = keywords(text);
    if (!text) continue;
    const member = { text, words, ref: r.ref, callId: r.call_id };
    const home = words.length ? groups.find((g) => g.members.some((m) => m.words.length && similar(m.words, words))) : undefined;
    if (home) home.members.push(member);
    else groups.push({ members: [member] });
  }
  return groups
    .map((g) => {
      const freq = new Map<string, number>();
      g.members.forEach((m) => m.words.forEach((w) => freq.set(w, (freq.get(w) ?? 0) + 1)));
      const shared = [...freq.entries()].filter(([, n]) => g.members.length === 1 || n >= 2).sort((a, b) => b[1] - a[1]).map(([w]) => w);
      const wordings = new Map<string, { text: string; n: number }>();
      g.members.forEach((m) => {
        const k = normalise(m.text);
        const cur = wordings.get(k);
        wordings.set(k, { text: cur?.text ?? m.text, n: (cur?.n ?? 0) + 1 });
      });
      return {
        keywords: shared.slice(0, 4),
        count: g.members.length,
        examples: [...wordings.values()].sort((a, b) => b.n - a.n).slice(0, MAX_EXAMPLES).map((w) => w.text),
        refs: g.members.map((m) => m.ref),
        callIds: [...new Set(g.members.flatMap((m) => (m.callId ? [m.callId] : [])))],
      };
    })
    .sort((a, b) => b.count - a.count);
}

/** Plain-text FAQ draft for the content team: the question, alternative wordings and where it came from. */
export function faqDraft(gap: FaqGap): string {
  const [question, ...others] = gap.examples;
  const lines = [`Q: ${question}`, 'A: (to be written and approved by the content team)'];
  if (others.length) lines.push('', 'Also asked as:', ...others.map((o) => `- ${o}`));
  lines.push('', `Asked ${gap.count} time${gap.count === 1 ? '' : 's'} (${gap.refs.join(', ')}).`);
  return lines.join('\n');
}
