import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SAMPLE_PROFILE } from '../api/mockSupport';
import { verifiedCustomerName, verifiedCustomerRef, type CustomerProfile, type SupportTurn } from '../api/support';
import { CustomerCard, formatDay, formatMobile } from './CustomerCard';

const turn = (retrieved: Record<string, unknown>): SupportTurn => ({ seq: 1, role: 'agent', text: '', at: '', meta: { retrieved } });

describe('CustomerCard', () => {
  it('shows the seeded details, holdings and requests', () => {
    render(<CustomerCard profile={SAMPLE_PROFILE} />);
    // N1: the full name leads as the card's heading; the CUST- id is secondary, small and muted.
    const name = screen.getByRole('heading', { name: 'Rahul Iyer' });
    const id = screen.getByText('CUST-1002');
    expect(id).toHaveClass('muted');
    expect(name.compareDocumentPosition(id) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText('97314 62580')).toBeInTheDocument();
    expect(screen.getByText('3 Nov 1985')).toBeInTheDocument();
    expect(screen.getByText('ACC-20002')).toBeInTheDocument();
    expect(screen.getByText('PL-31002')).toBeInTheDocument();
    expect(screen.getByText('VL-31003')).toBeInTheDocument();
    expect(screen.getByText('SR-40102')).toBeInTheDocument();
    expect(screen.queryByText('Complaints')).not.toBeInTheDocument();
  });

  it('shows where a service request sits and how it is going, and a complaint in the caller\'s own words', () => {
    const profile: CustomerProfile = {
      ...structuredClone(SAMPLE_PROFILE),
      tickets: [{ ref: 'SR-40102', category: 'STATEMENT', status: 'IN_PROGRESS', summary: 'Account statement request', department: 'Account Services', progress: 'Statement is being generated.' }],
      complaints: [{ ref: 'CMP-50200', category: 'UNAUTHORISED_TRANSACTION', status: 'OPEN', description: 'Card debit not made by the customer', escalated: true, original_statement: 'I never made this payment.', related_ref: 'TXN-90011' }],
    };
    render(<CustomerCard profile={profile} />);
    expect(screen.getByText(/Account Services/)).toBeInTheDocument();
    expect(screen.getByText(/Statement is being generated\./)).toBeInTheDocument();
    expect(screen.getByText('“I never made this payment.”')).toBeInTheDocument();
    expect(screen.getByText(/TXN-90011/)).toBeInTheDocument();
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
      customer: { customer_ref: 'CUST-1009', first_name: 'Karthik', last_name: 'Menon', mobile: '9380939280', dob: '1990-01-01' },
      accounts: [], loans: [], applications: [], transactions: [], policies: [], claims: [], tickets: [], complaints: [],
    };
    render(<CustomerCard profile={empty} />);
    expect(screen.getByText('93809 39280')).toBeInTheDocument();
    expect(screen.getByText('No accounts, loans, policies or requests on record.')).toBeInTheDocument();
  });

  it('formats mobiles and dates, leaving anything unexpected as is', () => {
    expect(formatMobile('9731462580')).toBe('97314 62580');
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

describe('verifiedCustomerName', () => {
  it('is the verified caller\'s name from the verify_customer result, and null before verification', () => {
    expect(verifiedCustomerName([])).toBeNull();
    expect(verifiedCustomerName([turn({ verify_customer: { verified: false, error: 'NO_MATCH' } })])).toBeNull();
    const first = turn({ verify_customer: { verified: true, customer: { customer_ref: 'CUST-1002', first_name: 'Rahul' } } });
    expect(verifiedCustomerName([first])).toBe('Rahul');
    const full = turn({ verify_customer: { verified: true, customer: { customer_ref: 'CUST-1002', first_name: 'Rahul', last_name: 'Iyer' } } });
    expect(verifiedCustomerName([full, turn({ get_loans: { items: [] } })])).toBe('Rahul Iyer');
  });
});
