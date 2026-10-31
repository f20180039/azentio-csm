import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import { ApiError } from '../api/errors';

type Tone = 'ok' | 'warn' | 'bad';
interface Toast {
  id: number;
  title: string;
  detail?: string;
  tone: Tone;
}

interface ToastCtx {
  push: (title: string, detail?: string, tone?: Tone) => void;
  error: (e: unknown) => void;
}

const Ctx = createContext<ToastCtx | null>(null);
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((title: string, detail?: string, tone: Tone = 'ok') => {
    const id = ++seq;
    setToasts((t) => [...t, { id, title, detail, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'bad' ? 7000 : 4000);
  }, []);

  const error = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError) push(e.title, e.detail, 'bad');
      else push('Something went wrong', e instanceof Error ? e.message : String(e), 'bad');
    },
    [push],
  );

  return (
    <Ctx.Provider value={{ push, error }}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <strong>{t.title}</strong>
            {t.detail && <span className="muted">{t.detail}</span>}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  const v = useContext(Ctx);
  if (!v) throw new Error('useToast outside ToastProvider');
  return v;
}
