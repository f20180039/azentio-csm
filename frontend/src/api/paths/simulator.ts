/** Bank simulator (backend/simulator), relative to SIMULATOR_BASE. */
export const SimulatorPath = {
  OPS_RECORDS: '/ops/records',
} as const;

/** One customer's seeded details and holdings, plus records raised in calls (ops credentials). */
export const opsCustomerPath = (customerRef: string) => `/ops/customers/${encodeURIComponent(customerRef)}`;

/** One service request: PATCH {status, progress} moves it (ops credentials). */
export const opsTicketPath = (ref: string) => `/ops/tickets/${encodeURIComponent(ref)}`;
