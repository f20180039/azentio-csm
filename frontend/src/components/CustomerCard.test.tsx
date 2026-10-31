import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SAMPLE_PROFILE } from '../api/mockSupport';
import { verifiedCustomerRef, type CustomerProfile, type SupportTurn } from '../api/support';
import { CustomerCard, formatDay, formatMobile } from './CustomerCard';

const turn = (retrieved: Record<string, unknown>): SupportTurn => ({ seq: 1, role: 'agent', text: '', at: '', meta: { retrieved } });

describe('CustomerCard', () => {
  it('shows the seeded details, holdings and requests', () => {
    render(<CustomerCard profile={SAMPLE_PROFILE} />);
    expect(screen.getByText('Rahul Iyer')).toBeInTheDocument();
    expect(screen.getByText('CUST-1002')).toBeInTheDocument();
    expect(screen.getByText('98765 00002')).toBeInTheDocument();
    expect(screen.getByText('3 Nov 1985')).toBeInTheDocument();
    expect(screen.getByText('ACC-20002')).toBeInTheDocument();
    expect(screen.getByText('PL-31002')).toBeInTheDocument();
    expect(screen.getByText('VL-31003')).toBeInTheDocument();
    expect(screen.getByText('SR-40102')).toBeInTheDocument();
    expect(screen.queryByText('Complaints')).not.toBeInTheDocument();
  });

  it('flags an overdue instalment and says when a customer holds nothing', () => {
    const overdue: CustomerProfile = {
      ...structuredClone(SAMPLE_PROFILE),
      loans: [{ ...SAMPLE_PROFILE.loans[0], overdue: { amount: 9800, since: '2026-10-22' } }],
    };
    const { unmount } = render(<CustomerCard profile={overdue} />);
    expect(screen.getByText(/overdue since 22 Oct 2026/)).toBeInTheDocument();
    unmount();

    const empty: CustomerProfile = {
      customer: { customer_ref: 'CUST-1009', first_name: 'Demo', last_name: 'Caller', mobile: '9380939280', dob: '1990-01-01' },
      accounts: [], loans: [], applications: [], transactions: [], policies: [], claims: [], tickets: [], complaints: [],
    };
    render(<CustomerCard profile={empty} />);
    expect(screen.getByText('93809 39280')).toBeInTheDocument();
    expect(screen.getByText('No accounts, loans, policies or requests on record.')).toBeInTheDocument();
  });

  it('formats mobiles and dates, leaving anything unexpected as is', () => {
    expect(formatMobile('9876500002')).toBe('98765 00002');
    expect(formatMobile('+91 98765')).toBe('+91 98765');
    expect(formatDay('1990-04-12')).toBe('12 Apr 1990');
    expect(formatDay('soon')).toBe('soon');
  });
});

describe('verifiedCustomerRef', () => {
  it('is null before verification and the latest verified customer after', () => {
    expect(verifiedCustomerRef([])).toBeNull();
    expect(verifiedCustomerRef([turn({ verify_customer: { verified: false, error: 'NO_MATCH' } })])).toBeNull();
    const ok = turn({ verify_customer: { verified: true, customer: { customer_ref: 'CUST-1002', first_name: 'Rahul' } } });
    expect(verifiedCustomerRef([ok, turn({ get_loans: { items: [] } })])).toBe('CUST-1002');
  });
});
