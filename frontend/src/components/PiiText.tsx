import { createContext, Fragment, useContext, type ReactNode } from 'react';
import type { PiiTokens } from '../api/support';
import { humanise } from '../format';
import { Highlight } from '../search';
import { PiiKind } from '../vocab';

export const PII_KIND_LABEL: Record<PiiKind, string> = {
  [PiiKind.MOBILE]: 'Mobile',
  [PiiKind.DOB]: 'Date of birth',
  [PiiKind.AADHAAR]: 'Aadhaar',
  [PiiKind.PAN]: 'PAN',
  [PiiKind.EMAIL]: 'E-mail',
  [PiiKind.CARD]: 'Card number',
  [PiiKind.ACCOUNT_NUMBER]: 'Account number',
  [PiiKind.DIGITS]: 'Digits',
  [PiiKind.NAME]: 'Name',
};

export function piiKindLabel(kind: string): string {
  return PII_KIND_LABEL[kind as PiiKind] ?? humanise(kind);
}

/** `[KIND#n]`, as the API writes it into stored turns, tool arguments, corrections and rating comments. */
const TOKEN_RE = new RegExp(`\\[(${Object.values(PiiKind).join('|')})#\\d+\\]`, 'g');

/**
 * Revealed values for the call on screen, or null while redacted. Component state only: whoever holds the
 * values keeps them in memory and drops them when the admin toggles the reveal off or leaves the call.
 */
const RevealCtx = createContext<PiiTokens | null>(null);

export function PiiRevealProvider({ value, children }: { value: PiiTokens | null; children: ReactNode }) {
  return <RevealCtx.Provider value={value}>{children}</RevealCtx.Provider>;
}

function Chip({ token, kind, note }: { token: string; kind: string; note: string }) {
  return (
    <span className="pill dim pii-chip" data-pii={token} title={`Personal data (${token}) is kept in the vault.`}>
      {piiKindLabel(kind)} ({note})
    </span>
  );
}

/**
 * Text that may carry `[KIND#n]` tokens. Each token renders as a grey "Mobile (redacted)" chip, or as the value
 * when `revealed` (or the nearest PiiRevealProvider) has it. Search hits are still marked, around the chips and
 * inside revealed values.
 */
export function PiiText({ text, revealed, query = '' }: { text: string; revealed?: PiiTokens | null; query?: string }): ReactNode {
  const fromContext = useContext(RevealCtx);
  const tokens = revealed ?? fromContext;
  const parts: ReactNode[] = [];
  let pos = 0;
  TOKEN_RE.lastIndex = 0;
  for (let m = TOKEN_RE.exec(text); m !== null; m = TOKEN_RE.exec(text)) {
    if (m.index > pos) parts.push(<Highlight key={pos} text={text.slice(pos, m.index)} query={query} />);
    const token = m[0];
    const kind = m[1];
    const held = tokens?.[token];
    if (held && typeof held.value === 'string') {
      parts.push(
        <span key={m.index} className="pii-value" data-pii={token} title={`${piiKindLabel(held.kind)} ${token}`}>
          <Highlight text={held.value} query={query} />
        </span>,
      );
    } else {
      parts.push(<Chip key={m.index} token={token} kind={held?.kind ?? kind} note={held ? 'not stored' : 'redacted'} />);
    }
    pos = m.index + token.length;
  }
  if (!parts.length) return <Highlight text={text} query={query} />;
  if (pos < text.length) parts.push(<Highlight key={pos} text={text.slice(pos)} query={query} />);
  return <Fragment>{parts}</Fragment>;
}
