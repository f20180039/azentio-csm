import { describe, expect, it } from 'vitest';
import { SAMPLE_RECORDS } from './api/mockSupport';
import { faqDraft, groupFaqGaps, keywords, normalise, queryText } from './faqGaps';

const rec = (ref: string, summary: string, call_id: string | null = null) => ({ ref, summary, call_id });

describe('FAQ gaps', () => {
  it('keeps only the customer words and normalises case and punctuation', () => {
    expect(queryText('Can you book me a flight to Dubai? — Travel booking is not a bank service')).toBe('Can you book me a flight to Dubai?');
    expect(normalise('  Book FLIGHT tickets, please!! ')).toBe('book flight tickets please');
    expect(keywords('Which stocks should I buy?')).toEqual(['stock', 'buy']);
  });

  it('groups similar wordings, counts them and keeps unrelated questions apart', () => {
    const gaps = groupFaqGaps([
      rec('RQ-1', 'Can you book me a flight to Dubai? — travel'),
      rec('RQ-2', 'Give me some stock tips. — advice'),
      rec('RQ-3', 'book flight tickets for me, please! — travel', 'call-9'),
      rec('RQ-4', 'Which stocks should I buy this week? — advice'),
      rec('RQ-5', 'What are your gold loan rates? — no FAQ'),
      rec('RQ-6', 'Gold loan interest rate? — no FAQ'),
      rec('RQ-7', 'BOOK A FLIGHT TO DUBAI — travel'),
      rec('RQ-8', 'What is my personal loan EMI? — no FAQ'),
    ]);
    const byRef = (r: string) => gaps.find((g) => g.refs.includes(r))!;
    expect(byRef('RQ-1').refs.sort()).toEqual(['RQ-1', 'RQ-3', 'RQ-7']);
    expect(byRef('RQ-1').count).toBe(3);
    expect(byRef('RQ-1').keywords).toEqual(expect.arrayContaining(['book', 'flight']));
    expect(byRef('RQ-1').callIds).toEqual(['call-9']);
    expect(byRef('RQ-2').refs.sort()).toEqual(['RQ-2', 'RQ-4']);
    expect(byRef('RQ-5').refs.sort()).toEqual(['RQ-5', 'RQ-6']);
    expect(byRef('RQ-8').refs).toEqual(['RQ-8']);
    expect(gaps[0].count).toBe(3);
    expect(gaps.map((g) => g.count)).toEqual([...gaps.map((g) => g.count)].sort((a, b) => b - a));
  });

  it('collapses identical wordings into one example', () => {
    const [g] = groupFaqGaps([rec('RQ-1', 'Stock tips?'), rec('RQ-2', 'stock tips'), rec('RQ-3', 'Stock tips please')]);
    expect(g.count).toBe(3);
    expect(g.examples).toEqual(['Stock tips?', 'Stock tips please']);
  });

  it('writes an FAQ draft with the main question, other wordings and references', () => {
    const gaps = groupFaqGaps(SAMPLE_RECORDS.routed);
    const draft = faqDraft(gaps[0]);
    expect(draft).toMatch(/^Q: /);
    expect(draft).toContain('Also asked as:');
    expect(draft).toContain(`Asked ${gaps[0].count} times`);
  });
});
