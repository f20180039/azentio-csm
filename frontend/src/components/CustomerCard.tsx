import type { ReactNode } from 'react';
import type { CustomerProfile } from '../api/support';
import { formatInr, humanise } from '../format';
import { TxnDirection } from '../vocab';

/** The tooltip on a CUST- id wherever the panel shows one as secondary text (the card, the desk rows, the call screen). */
export const CUSTOMER_ID_LABEL = 'Customer ID';

/** '9731462580' → '97314 62580', the way callers say it. */
export function formatMobile(mobile: string): string {
  return /^\d{10}$/.test(mobile) ? `${mobile.slice(0, 5)} ${mobile.slice(5)}` : mobile;
}

/** '1985-11-03' → '3 Nov 1985'. */
export function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function Group({ title, children }: { title: string; children: ReactNode[] }) {
  if (children.length === 0) return null;
  return (
    <div className="cust-group">
      <h3 className="small muted">{title}</h3>
      <ul>{children}</ul>
    </div>
  );
}

function Row({ id, main, detail }: { id: string; main: ReactNode; detail?: ReactNode }) {
  return (
    <li>
      <span className="mono small">{id}</span> {main}
      {detail && <div className="small muted">{detail}</div>}
    </li>
  );
}

/** What the bank holds for the verified caller: the seeded details and holdings, plus anything raised on calls. */
export function CustomerCard({ profile }: { profile: CustomerProfile }) {
  const c = profile.customer;
  const holdings =
    profile.accounts.length + profile.loans.length + profile.applications.length + profile.policies.length + profile.claims.length +
    profile.tickets.length + profile.complaints.length + profile.transactions.length;
  return (
    <div className="cust-card">
      {/* People see names, not ids: the full name leads; the customer id is a secondary fact for staff cross-referencing. */}
      <h3 className="cust-name">
        {c.first_name} {c.last_name}
      </h3>
      <dl className="facts">
        <dt>Customer</dt>
        <dd className="mono small muted" title={CUSTOMER_ID_LABEL}>
          {c.customer_ref}
        </dd>
        <dt>Mobile</dt>
        <dd className="num">{formatMobile(c.mobile)}</dd>
        <dt>Date of birth</dt>
        <dd className="num">{formatDay(c.dob)}</dd>
      </dl>
      {holdings === 0 && <p className="small muted">No accounts, loans, policies or requests on record.</p>}
      <Group title="Accounts">
        {profile.accounts.map((a) => (
          <Row key={a.account_id} id={a.account_id} main={`${humanise(a.type)} ${a.masked_number}`} detail={`Balance ${formatInr(a.balance)}`} />
        ))}
      </Group>
      <Group title="Loans">
        {profile.loans.map((l) => (
          <Row
            key={l.loan_id}
            id={l.loan_id}
            main={`${l.product} · ${humanise(l.status)}`}
            detail={
              <>
                Outstanding {formatInr(l.outstanding_principal)}
                {l.next_instalment && ` · next EMI ${formatInr(l.next_instalment.amount)} on ${formatDay(l.next_instalment.due_date)}`}
                {l.overdue && <strong className="cust-overdue"> · {formatInr(l.overdue.amount)} overdue since {formatDay(l.overdue.since)}</strong>}
              </>
            }
          />
        ))}
      </Group>
      <Group title="Loan applications">
        {profile.applications.map((a) => (
          <Row key={a.ref} id={a.ref} main={`${a.product} · ${a.stage_label}`} detail={`${formatInr(a.amount)}, submitted ${formatDay(a.submitted_on)}`} />
        ))}
      </Group>
      <Group title="Insurance">
        {[
          ...profile.policies.map((p) => (
            <Row key={p.policy_no} id={p.policy_no} main={`${p.product} · ${p.coverage_status}`} detail={`Premium ${formatInr(p.premium)}`} />
          )),
          ...profile.claims.map((cl) => (
            <Row key={cl.claim_no} id={cl.claim_no} main={`Claim on ${cl.policy_no} · ${humanise(cl.status)}`} detail={`Claimed ${formatInr(cl.amount_claimed)}`} />
          )),
        ]}
      </Group>
      <Group title="Service requests">
        {profile.tickets.map((t) => (
          <Row
            key={t.ref}
            id={t.ref}
            main={`${humanise(t.category)} · ${humanise(t.status)}${t.department ? ` · ${t.department}` : ''}`}
            detail={
              <>
                {t.summary}
                {t.progress && <div>{t.progress}</div>}
              </>
            }
          />
        ))}
      </Group>
      <Group title="Complaints">
        {profile.complaints.map((cm) => (
          <Row
            key={cm.ref}
            id={cm.ref}
            main={`${humanise(cm.category)} · ${humanise(cm.status)}${cm.escalated ? ' · escalated' : ''}`}
            detail={
              <>
                {cm.description}
                {cm.related_ref && ` · about ${cm.related_ref}`}
                {cm.original_statement && <div className="cust-quote">{`“${cm.original_statement}”`}</div>}
              </>
            }
          />
        ))}
      </Group>
      <Group title="Recent transactions">
        {profile.transactions.map((t) => (
          <Row
            key={t.ref}
            id={t.ref}
            main={`${t.direction === TxnDirection.CREDIT ? '+' : '−'}${formatInr(t.amount)} · ${humanise(t.status)}`}
            detail={`${t.description}, ${formatDay(t.date)}`}
          />
        ))}
      </Group>
    </div>
  );
}
