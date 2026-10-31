import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { SearchParam } from '../search';

export const SEARCH_DEBOUNCE_MS = 120;

/** Params this module wrote but the router may not have rendered yet: two boxes can fire in the same tick. */
let pending: { params: URLSearchParams; at: number } | null = null;
const PENDING_MS = 100;

/** The search query kept in the URL (?q=), merged into whatever other params the page already uses. */
export function useUrlQuery(param: SearchParam = SearchParam.QUERY): [string, (q: string) => void] {
  const [params, setParams] = useSearchParams();
  const latest = useRef({ params, setParams });
  latest.current = { params, setParams };
  const query = params.get(param) ?? '';
  const setQuery = useCallback(
    (q: string) => {
      const fresh = pending && Date.now() - pending.at < PENDING_MS ? pending.params : latest.current.params;
      const next = new URLSearchParams(fresh);
      if (q.trim()) next.set(param, q);
      else next.delete(param);
      pending = { params: next, at: Date.now() };
      latest.current.setParams(next, { replace: true });
    },
    [param],
  );
  return [query, setQuery];
}

function typingElsewhere(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.getAttribute('role') === 'listbox';
}

interface SearchBoxProps {
  value: string;
  onChange: (q: string) => void;
  label: string;
  placeholder: string;
  /** Items shown after filtering, and before. The count is hidden until both are known. */
  shown?: number;
  total?: number;
  /** "/" focuses this box; give it to one box per page. */
  shortcut?: boolean;
  className?: string;
}

export function SearchBox({ value, onChange, label, placeholder, shown, total, shortcut = true, className }: SearchBoxProps) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState(value);
  const emitted = useRef(value);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (value !== emitted.current) {
      emitted.current = value;
      setText(value);
    }
  }, [value]);

  useEffect(() => () => clearTimeout(timer.current), []);

  const emit = useCallback(
    (q: string) => {
      clearTimeout(timer.current);
      emitted.current = q;
      onChangeRef.current(q);
    },
    [],
  );

  function type(q: string) {
    setText(q);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => emit(q), SEARCH_DEBOUNCE_MS);
  }

  function clear() {
    setText('');
    emit('');
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    clear();
    input.current?.blur();
  }

  useEffect(() => {
    if (!shortcut) return;
    const onSlash = (e: globalThis.KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || typingElsewhere(e.target)) return;
      e.preventDefault();
      input.current?.focus();
    };
    window.addEventListener('keydown', onSlash);
    return () => window.removeEventListener('keydown', onSlash);
  }, [shortcut]);

  const active = value.trim() !== '';
  const showCount = active && shown != null && total != null;

  return (
    <div className={`search${className ? ` ${className}` : ''}`} role="search">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <div className="search-field">
      <svg className="search-icon" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="7" cy="7" r="4.6" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
      <input
        ref={input}
        id={id}
        type="search"
        className="search-input"
        value={text}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => type(e.target.value)}
        onKeyDown={onKey}
      />
      {text ? (
        <button
          type="button"
          className="search-clear"
          aria-label="Clear search text"
          onClick={() => {
            clear();
            input.current?.focus();
          }}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </button>
      ) : (
        shortcut && (
          <kbd className="search-kbd" aria-hidden="true">
            /
          </kbd>
        )
      )}
      </div>
      <span className="search-count" aria-live="polite">
        {showCount ? `${shown} of ${total}` : ''}
      </span>
    </div>
  );
}

/** Empty state for a search that matched nothing. */
export function NoResults({ query, onClear }: { query: string; onClear: () => void }) {
  return (
    <div className="empty">
      <strong>No results for ‘{query.trim()}’</strong>
      <span>Check the spelling, or search by another field.</span>
      <button type="button" className="btn" onClick={onClear}>
        Clear search
      </button>
    </div>
  );
}
