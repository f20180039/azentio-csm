import { describe, expect, it } from 'vitest';
import { SAMPLE_ROUTED_CALL, SAMPLE_VERIFIED_CALL } from './api/mockSupport';
import { scenarioYaml } from './scenarioExport';

describe('scenarioYaml', () => {
  it('turns each customer turn into say + expect, with outcome counts from the refs', () => {
    const y = scenarioYaml(SAMPLE_VERIFIED_CALL);
    const lines = y.split('\n');
    expect(lines[0]).toBe('id: reviewed-sample-call-repayment');
    expect(lines[1]).toBe('title: "Reviewed call sample-call-repayment"');
    expect(lines[2]).toBe('turns:');
    expect(y).toContain('  - say: "Hi, when is my next EMI due?"\n    expect: {intents: [REPAYMENT]}');
    expect(y).toContain('    expect: {intents: [REPAYMENT], verified: true}');
    expect(y.match(/verified: true/g)).toHaveLength(1);
    expect(y.match(/- say:/g)).toHaveLength(4);
    expect(y).not.toContain('Thank you, Rahul');
    expect(y.trimEnd().split('\n').pop()).toBe('outcome: {tickets: 1, complaints: 0, routed: 0, escalations: 0}');
  });

  it('skips no-speech turns, escapes quotes and adds reviewer corrections as comments', () => {
    const call = structuredClone(SAMPLE_ROUTED_CALL);
    call.turns[1].text = 'What is the "gold rate" today?';
    const y = scenarioYaml(call);
    expect(y.match(/- say:/g)).toHaveLength(1);
    expect(y).toContain('  - say: "What is the \\"gold rate\\" today?"');
    expect(y).toContain('    # reviewer (reviewer) says it should have said: Say that live gold prices');
    expect(y).toContain('outcome: {tickets: 0, complaints: 0, routed: 1, escalations: 0}');
  });

  it('writes an empty turn list for a call with no customer speech', () => {
    expect(scenarioYaml({ id: 'x', outcome: null, turns: [] })).toContain('turns:\n  []\n');
  });
});
