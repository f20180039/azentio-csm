import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';

/** Writes text to the clipboard; false when the browser refuses (insecure origin, sandboxed viewer). */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Shows text to copy instead of downloading a file, since some viewers block downloads. */
export function CopyDialog({ title, note, text, onClose }: { title: string; note?: string; text: string; onClose: () => void }) {
  const id = useId();
  const [copied, setCopied] = useState<'idle' | 'ok' | 'failed'>('idle');
  const area = useRef<HTMLTextAreaElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => closeBtn.current?.focus(), []);
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  };
  async function copy() {
    const ok = await copyText(text);
    setCopied(ok ? 'ok' : 'failed');
    if (!ok) area.current?.select();
  }
  return (
    <div className="overlay" onKeyDown={onKey}>
      <div className="dialog copy-dialog" role="dialog" aria-modal="true" aria-labelledby={`${id}-t`}>
        <h2 id={`${id}-t`}>{title}</h2>
        {note && <p className="small muted">{note}</p>}
        <textarea ref={area} readOnly value={text} aria-label={title} className="copy-text" rows={Math.min(18, text.split('\n').length + 1)} />
        <div className="dialog-actions">
          <span className="small muted copy-status" role="status">
            {copied === 'ok' ? 'Copied to the clipboard.' : copied === 'failed' ? 'Copy was blocked; the text is selected, press ⌘C or Ctrl+C.' : ''}
          </span>
          <button ref={closeBtn} type="button" className="btn" onClick={onClose}>
            Close
          </button>
          <button type="button" className="btn primary" onClick={() => void copy()}>
            Copy
          </button>
        </div>
      </div>
    </div>
  );
}
