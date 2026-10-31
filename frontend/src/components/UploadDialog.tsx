import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { api } from '../api/client';
import type { RulePackInfo, UploadResult } from '../api/types';
import { humanise } from '../format';
import { Select } from './Select';
import { useToast } from './Toasts';

const MAX_BYTES = 20 * 1024 * 1024;

export function UploadDialog({ onClose, onUploaded }: { onClose: () => void; onUploaded: (r: UploadResult) => void }) {
  const [packs, setPacks] = useState<RulePackInfo[]>([]);
  const [caseType, setCaseType] = useState('');
  const [title, setTitle] = useState('');
  const [attributes, setAttributes] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  useEffect(() => {
    api
      .listPacks()
      .then((p) => {
        setPacks(p);
        if (p.length) setCaseType(p[0].caseType);
      })
      .catch(toast.error);
  }, [toast.error]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const tooBig = files.filter((f) => f.size > MAX_BYTES);
  const attributesError = validateAttributes(attributes);

  function addFiles(list: FileList | null) {
    if (!list) return;
    setFiles((prev) => [...prev, ...Array.from(list).filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))]);
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    addFiles(e.dataTransfer.files);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!files.length || !caseType || tooBig.length || attributesError) return;
    setBusy(true);
    try {
      const r = await api.uploadCase(files, caseType, title.trim() || undefined, attributes.trim() || undefined);
      toast.push(
        r.cache === 'HIT' ? 'Already processed: opened the existing case' : 'Uploaded and queued',
        r.cache === 'HIT'
          ? 'Same file and pipeline version, so no new processing or model cost.'
          : `${files.length} file${files.length > 1 ? 's' : ''} queued for extraction and scoring.`,
        r.cache === 'HIT' ? 'warn' : 'ok',
      );
      onUploaded(r);
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="upload-title" onSubmit={submit}>
        <div>
          <h2 id="upload-title">New case</h2>
          <p className="muted small">PDFs up to 20 MB and 50 pages each. Re-uploading the same file returns the existing case.</p>
        </div>
        <div className="field">
          <label htmlFor="upload-type">Case type</label>
          <Select id="upload-type" value={caseType} onChange={setCaseType} options={packs.map((p) => ({ value: p.caseType, label: p.label ?? humanise(p.caseType) }))} />
        </div>
        <div className="field">
          <label htmlFor="upload-title-input">Title (optional)</label>
          <input id="upload-title-input" type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Applicant name · loan amount" />
        </div>
        <div className="field">
          <label htmlFor="upload-attributes">Case details (optional, JSON)</label>
          <textarea
            id="upload-attributes"
            className="mono small"
            value={attributes}
            onChange={(e) => setAttributes(e.target.value)}
            placeholder='{"policyNo": "POL-88123401", "declaredMonthlyIncome": 85000}'
            aria-invalid={attributesError ? true : undefined}
            aria-describedby={attributesError ? 'upload-attributes-error' : undefined}
          />
          {attributesError && (
            <span id="upload-attributes-error" className="small" role="alert">
              {attributesError}
            </span>
          )}
        </div>
        <div
          className={`dropzone ${dragging ? 'active' : ''}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
        >
          <UploadIcon />
          <strong>Drop PDFs here</strong>
          <span className="small">Bank statements, bills, invoices, circulars</span>
          <span className="btn sm dropzone-btn" aria-hidden="true">Choose files</span>
          <input id="upload-files" ref={inputRef} type="file" multiple accept="application/pdf,.pdf" hidden onChange={(e) => addFiles(e.target.files)} />
        </div>
        {files.length > 0 && (
          <div className="file-list">
            {files.map((f) => (
              <div key={f.name + f.size}>
                <span className="mono">{f.name}</span>
                <span className={f.size > MAX_BYTES ? 'pill bad' : 'muted num'}>
                  {f.size > MAX_BYTES ? 'Over 20 MB' : `${(f.size / 1024).toFixed(0)} KB`}
                </span>
              </div>
            ))}
          </div>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy || !files.length || !caseType || tooBig.length > 0 || !!attributesError}>
            {busy ? 'Uploading…' : `Upload ${files.length || ''} ${files.length === 1 ? 'file' : 'files'}`.replace('  ', ' ')}
          </button>
        </div>
      </form>
    </div>
  );
}

function validateAttributes(raw: string): string | null {
  if (!raw.trim()) return null;
  try {
    const v: unknown = JSON.parse(raw);
    return v !== null && typeof v === 'object' && !Array.isArray(v) ? null : 'Enter a JSON object, for example {"policyNo": "POL-1"}.';
  } catch {
    return 'This is not valid JSON. Check quotes and commas.';
  }
}

function UploadIcon() {
  return (
    <svg className="dropzone-icon" viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
    </svg>
  );
}
