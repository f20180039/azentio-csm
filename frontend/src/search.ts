import { createElement, Fragment, type ReactNode } from 'react';
import { intentLabel, type SupportTurn } from './api/support';

/** URL search params owned by the search boxes. */
export const SearchParam = { QUERY: 'q', RECORDS_QUERY: 'rq' } as const;
export type SearchParam = (typeof SearchParam)[keyof typeof SearchParam];

export type SearchField = string | number | null | undefined | readonly SearchField[];

const MARKS = /\p{M}/gu;

/** Lower-case, accent-free, with enum underscores read as spaces: TICKET_CREATED → "ticket created". */
export function normalise(s: string): string {
  return s.normalize('NFD').replace(MARKS, '').toLowerCase().replace(/_/g, ' ');
}

export function searchTerms(query: string): string[] {
  return normalise(query).split(/\s+/).filter(Boolean);
}

function flatten(fields: readonly SearchField[], out: string[] = []): string[] {
  for (const f of fields) {
    if (f == null) continue;
    if (Array.isArray(f)) flatten(f, out);
    else out.push(normalise(String(f)));
  }
  return out;
}

/** True when every space-separated term of the query appears in some field. An empty query matches everything. */
export function matches(query: string, ...fields: SearchField[]): boolean {
  const terms = searchTerms(query);
  if (!terms.length) return true;
  const haystack = flatten(fields);
  return terms.every((t) => haystack.some((h) => h.includes(t)));
}

/**
 * A conversation turn matches on its words, a reviewer's corrected reading of them, their English (when translated),
 * its intents by code and label, and its references.
 */
export function turnMatches(q: string, t: SupportTurn): boolean {
  const intents = t.meta.intents ?? [];
  return matches(q, t.text, t.meta.transcript_correction?.text, t.meta.text_en, intents, intents.map(intentLabel), t.meta.refs);
}

/** Normalises text char by char, keeping where each normalised char came from, so hits map back to the original. */
function indexed(text: string): { norm: string; from: number[] } {
  let norm = '';
  const from: number[] = [];
  for (let i = 0; i < text.length; ) {
    const cp = text.codePointAt(i)!;
    const ch = String.fromCodePoint(cp);
    const n = normalise(ch);
    norm += n;
    for (let k = 0; k < n.length; k++) from.push(i);
    i += ch.length;
  }
  from.push(text.length);
  return { norm, from };
}

/** [start, end) ranges of the original text that match any query term, merged. */
export function hitRanges(text: string, query: string): [number, number][] {
  const terms = searchTerms(query);
  if (!terms.length || !text) return [];
  const { norm, from } = indexed(text);
  const raw: [number, number][] = [];
  for (const t of terms) {
    for (let at = norm.indexOf(t); at !== -1; at = norm.indexOf(t, at + t.length)) {
      raw.push([from[at], from[at + t.length]]);
    }
  }
  raw.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const r of raw) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([...r]);
  }
  return merged;
}

/** Renders text with the query's matches wrapped in <mark>. */
export function Highlight({ text, query }: { text: string; query: string }): ReactNode {
  const ranges = hitRanges(text, query);
  if (!ranges.length) return text;
  const parts: ReactNode[] = [];
  let pos = 0;
  ranges.forEach(([s, e], i) => {
    if (s > pos) parts.push(text.slice(pos, s));
    parts.push(createElement('mark', { key: i, className: 'search-hit' }, text.slice(s, e)));
    pos = e;
  });
  if (pos < text.length) parts.push(text.slice(pos));
  return createElement(Fragment, null, ...parts);
}
