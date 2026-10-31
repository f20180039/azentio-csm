import { describe, expect, it } from 'vitest';
import { Route } from './routes';
import { CaseType } from './vocab';

describe('Route.caseOrCall', () => {
  it('opens a support call case on its call page, and any other case in the case workspace', () => {
    expect(Route.caseOrCall({ id: 'b60e', caseType: CaseType.SUPPORT_CALL })).toBe('/support/calls/b60e');
    expect(Route.caseOrCall({ id: 'c1', caseType: 'insurance_claim' })).toBe('/cases/c1');
  });
});
