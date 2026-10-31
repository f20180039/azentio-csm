import { Role } from './vocab';

/** The three demo accounts, each shown as a team member. Usernames are the API's accounts (password = username). */
export const DEMO_USERS = [
  { username: 'admin', name: 'Anshuman', role: 'Admin', primary: Role.ADMIN, initials: 'AS', can: 'Full access, including the audit chain.' },
  { username: 'reviewer', name: 'Chirag', role: 'Reviewer', primary: Role.REVIEWER, initials: 'CH', can: 'Decides findings and cases.' },
  { username: 'analyst', name: 'Pavan', role: 'Analyst', primary: Role.ANALYST, initials: 'PM', can: 'Follows calls and opens cases.' },
] as const;

export type DemoUser = (typeof DEMO_USERS)[number];

/** The person behind a username, for the header; unknown accounts show the username itself. */
export function displayName(username: string): string {
  return DEMO_USERS.find((u) => u.username === username)?.name ?? username;
}

/** True for the signed-in account the API treats as an administrator (the API still enforces this on every request). */
export function isDemoAdmin(username: string | null): boolean {
  return DEMO_USERS.find((u) => u.username === username)?.primary === Role.ADMIN;
}
