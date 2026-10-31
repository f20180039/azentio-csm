import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

interface SelectProps {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  id?: string;
  'aria-label'?: string;
  disabled?: boolean;
  icon?: ReactNode;
  /** 'dark' for use on the navy top bar */
  tone?: 'dark';
  className?: string;
}

const TYPEAHEAD_MS = 600;

/** A themed listbox that replaces the native select: button + popup listbox, rendered in a portal so tables and dialogs never clip it. */
export function Select({ value, options, onChange, id, 'aria-label': ariaLabel, disabled, icon, tone, className }: SelectProps) {
  const uid = useId();
  const listId = `${uid}-list`;
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<{ top: number; left: number; minWidth: number; up: boolean } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const typed = useRef({ text: '', at: 0 });

  const selectedIndex = options.findIndex((o) => o.value === value);
  const selected = options[selectedIndex];

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) button.current?.focus();
  }, []);

  function show(at = selectedIndex) {
    if (disabled || !options.length) return;
    setActive(at < 0 ? 0 : at);
    setOpen(true);
  }

  function choose(i: number) {
    const o = options[i];
    if (!o || o.disabled) return;
    if (o.value !== value) onChange(o.value);
    close(true);
  }

  function step(from: number, dir: 1 | -1): number {
    for (let i = from + dir; i >= 0 && i < options.length; i += dir) if (!options[i].disabled) return i;
    return from;
  }

  function typeAhead(key: string, from: number): number {
    const now = Date.now();
    const t = typed.current;
    t.text = now - t.at > TYPEAHEAD_MS ? key : t.text + key;
    t.at = now;
    const q = t.text.toLowerCase();
    const start = t.text.length === 1 ? from + 1 : from;
    for (let n = 0; n < options.length; n++) {
      const i = (start + n) % options.length;
      if (!options[i].disabled && options[i].label.toLowerCase().startsWith(q)) return i;
    }
    return from;
  }

  function onButtonKey(e: KeyboardEvent) {
    if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
      e.preventDefault();
      show();
    } else if (e.key.length === 1 && /\S/.test(e.key)) {
      const i = typeAhead(e.key, selectedIndex);
      if (i !== selectedIndex && options[i].value !== value) onChange(options[i].value);
    }
  }

  function onListKey(e: KeyboardEvent) {
    const keys: Record<string, () => void> = {
      ArrowDown: () => setActive((a) => step(a, 1)),
      ArrowUp: () => setActive((a) => step(a, -1)),
      Home: () => setActive(step(-1, 1)),
      End: () => setActive(step(options.length, -1)),
      Enter: () => choose(active),
      ' ': () => choose(active),
      Escape: () => close(true),
    };
    if (keys[e.key]) {
      e.preventDefault();
      keys[e.key]();
    } else if (e.key === 'Tab') {
      close(true);
    } else if (e.key.length === 1 && /\S/.test(e.key)) {
      setActive((a) => typeAhead(e.key, a));
    }
  }

  const place = useCallback(() => {
    const b = button.current?.getBoundingClientRect();
    const l = list.current;
    if (!b || !l) return;
    const h = Math.min(l.scrollHeight, 320);
    const below = window.innerHeight - b.bottom;
    const up = below < h + 12 && b.top > below;
    const left = Math.max(8, Math.min(b.left, window.innerWidth - l.offsetWidth - 8));
    setPos({ top: up ? Math.max(8, b.top - h - 6) : b.bottom + 6, left, minWidth: b.width, up });
  }, []);

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    place();
    list.current?.focus({ preventScroll: true });
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    const outside = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!button.current?.contains(t) && !list.current?.contains(t)) close(false);
    };
    window.addEventListener('mousedown', outside);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('mousedown', outside);
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open, close, place]);

  useEffect(() => {
    if (open) list.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView?.({ block: 'nearest' });
  }, [open, active]);

  return (
    <div className={`dd${tone === 'dark' ? ' dd-dark' : ''}${open ? ' is-open' : ''}${className ? ` ${className}` : ''}`}>
      <button
        ref={button}
        type="button"
        id={id}
        className="dd-btn"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        disabled={disabled}
        onClick={() => (open ? close(true) : show())}
        onKeyDown={onButtonKey}
      >
        {icon && (
          <span className="dd-icon" aria-hidden="true">
            {icon}
          </span>
        )}
        <span className="dd-value">{selected?.label ?? ''}</span>
        <svg className="dd-chev" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open &&
        createPortal(
          <ul
            ref={list}
            id={listId}
            role="listbox"
            tabIndex={-1}
            aria-label={ariaLabel}
            aria-labelledby={ariaLabel ? undefined : id}
            aria-activedescendant={`${uid}-opt-${active}`}
            className={`dd-list${tone === 'dark' ? ' dd-dark' : ''}${pos?.up ? ' up' : ''}`}
            style={pos ? { top: pos.top, left: pos.left, minWidth: pos.minWidth } : { visibility: 'hidden', top: 0, left: 0 }}
            onKeyDown={onListKey}
          >
            {options.map((o, i) => (
              <li
                key={o.value}
                id={`${uid}-opt-${i}`}
                data-i={i}
                role="option"
                aria-selected={o.value === value}
                aria-disabled={o.disabled || undefined}
                className={`dd-opt${i === active ? ' is-active' : ''}`}
                onMouseMove={() => i !== active && !o.disabled && setActive(i)}
                onClick={() => choose(i)}
              >
                <svg className="dd-tick" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span>{o.label}</span>
              </li>
            ))}
          </ul>,
          document.body,
        )}
    </div>
  );
}
