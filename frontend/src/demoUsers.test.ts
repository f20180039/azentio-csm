import { describe, expect, it } from 'vitest';
import { DEMO_USERS, displayName } from './demoUsers';

describe('demo users', () => {
  it('shows each account as a team member and falls back to the username', () => {
    expect(DEMO_USERS.map((u) => [u.username, u.name, u.role])).toEqual([
      ['admin', 'Anshuman', 'Admin'], ['reviewer', 'Chirag', 'Reviewer'], ['analyst', 'Pavan', 'Analyst'],
    ]);
    expect(displayName('reviewer')).toBe('Chirag');
    expect(displayName('voice')).toBe('voice');
  });
});
