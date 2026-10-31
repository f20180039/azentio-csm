import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PiiKind } from '../vocab';
import { PII_KIND_LABEL, PiiRevealProvider, PiiText } from './PiiText';

const MOBILE_TOKEN = '[MOBILE#1]';
const REVEALED = { [MOBILE_TOKEN]: { kind: PiiKind.MOBILE, value: '9876500002' } };

describe('PiiText', () => {
  it('shows a [MOBILE#1] token as a grey "Mobile (redacted)" chip, never the token itself', () => {
    render(<PiiText text={`It is ${MOBILE_TOKEN}, call me.`} revealed={null} />);
    const chip = screen.getByText('Mobile (redacted)');
    expect(chip).toHaveClass('pill', 'dim');
    expect(chip).toHaveAttribute('data-pii', MOBILE_TOKEN);
    expect(screen.queryByText(/\[MOBILE#1\]/)).not.toBeInTheDocument();
    expect(screen.getByText(/It is/)).toHaveTextContent('It is Mobile (redacted), call me.');
  });

  it('shows the value once revealed has the token', () => {
    render(<PiiText text={`It is ${MOBILE_TOKEN}.`} revealed={REVEALED} />);
    expect(screen.getByText('9876500002')).toBeInTheDocument();
    expect(screen.queryByText('Mobile (redacted)')).not.toBeInTheDocument();
  });

  it('says the value is not stored when the vault returned null for it', () => {
    render(<PiiText text={MOBILE_TOKEN} revealed={{ [MOBILE_TOKEN]: { kind: PiiKind.MOBILE, value: null } }} />);
    expect(screen.getByText('Mobile (not stored)')).toBeInTheDocument();
  });

  it('labels every kind and keeps an unknown kind readable', () => {
    render(<PiiText text="[DOB#2] [ACCOUNT_NUMBER#1]" revealed={null} />);
    expect(screen.getByText(`${PII_KIND_LABEL[PiiKind.DOB]} (redacted)`)).toBeInTheDocument();
    expect(screen.getByText(`${PII_KIND_LABEL[PiiKind.ACCOUNT_NUMBER]} (redacted)`)).toBeInTheDocument();
    expect(Object.keys(PII_KIND_LABEL).sort()).toEqual(Object.values(PiiKind).sort());
  });

  it('still highlights search hits in the text around the chips and inside revealed values', () => {
    const { container, rerender } = render(<PiiText text={`Call ${MOBILE_TOKEN} today`} revealed={null} query="today" />);
    expect(container.querySelector('mark.search-hit')).toHaveTextContent('today');
    expect(screen.getByText('Mobile (redacted)')).toBeInTheDocument();

    rerender(<PiiText text={`Call ${MOBILE_TOKEN} today`} revealed={REVEALED} query="9876" />);
    expect(container.querySelector('mark.search-hit')).toHaveTextContent('9876');
  });

  it('renders plain text untouched when there is no token', () => {
    render(<PiiText text="When is my next EMI?" revealed={null} />);
    expect(screen.getByText('When is my next EMI?')).toBeInTheDocument();
  });

  it('falls back to the nearest PiiRevealProvider when no revealed prop is given', () => {
    render(
      <PiiRevealProvider value={REVEALED}>
        <PiiText text={MOBILE_TOKEN} />
      </PiiRevealProvider>,
    );
    expect(screen.getByText('9876500002')).toBeInTheDocument();
  });
});
