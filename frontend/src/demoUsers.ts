/** The three demo accounts, each shown as a team member. Usernames are the API's accounts (password = username). */
export const DEMO_USERS = [
  { username: 'admin', name: 'Anshuman', role: 'Admin', initials: 'AS', can: 'Full access, including the audit chain.' },
  { username: 'reviewer', name: 'Chirag', role: 'Reviewer', initials: 'CH', can: 'Decides findings and cases.' },
  { username: 'analyst', name: 'Pavan', role: 'Analyst', initials: 'PM', can: 'Follows calls and opens cases.' },
] as const;

export type DemoUser = (typeof DEMO_USERS)[number];

/** The person behind a username, for the header; unknown accounts show the username itself. */
export function displayName(username: string): string {
  return DEMO_USERS.find((u) => u.username === username)?.name ?? username;
}
