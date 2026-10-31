import { useState, type KeyboardEvent } from 'react';

const MAX = 5;
const STAR = 'M8 1.2l2.1 4.3 4.7.7-3.4 3.3.8 4.7L8 12l-4.2 2.2.8-4.7L1.2 6.2l4.7-.7z';

function Star({ on, size }: { on: boolean; size: number }) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} aria-hidden="true" className={`star${on ? ' on' : ''}`}>
      <path d={STAR} />
    </svg>
  );
}

/** Read-only star rating. */
export function Stars({ score, size = 14 }: { score: number; size?: number }) {
  return (
    <span className="stars" role="img" aria-label={`${score} out of ${MAX} stars`} title={`${score} / ${MAX}`}>
      {Array.from({ length: MAX }, (_, i) => (
        <Star key={i} on={i < score} size={size} />
      ))}
    </span>
  );
}

/** A 1–5 star picker: a radio group with arrow-key support and hover preview. */
export function StarInput({ value, onChange, disabled }: { value: number; onChange: (n: number) => void; disabled?: boolean }) {
  const [hover, setHover] = useState(0);
  const shown = hover || value;
  const onKey = (e: KeyboardEvent) => {
    const d = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    onChange(Math.min(MAX, Math.max(1, (value || 0) + d)));
  };
  return (
    <span className="star-input" role="radiogroup" aria-label="Rating" onMouseLeave={() => setHover(0)} onKeyDown={onKey}>
      {Array.from({ length: MAX }, (_, i) => {
        const n = i + 1;
        return (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={value === n}
            aria-label={`${n} star${n > 1 ? 's' : ''}`}
            tabIndex={value === n || (!value && n === 1) ? 0 : -1}
            disabled={disabled}
            onMouseEnter={() => setHover(n)}
            onClick={() => onChange(n)}
          >
            <Star on={n <= shown} size={22} />
          </button>
        );
      })}
    </span>
  );
}
