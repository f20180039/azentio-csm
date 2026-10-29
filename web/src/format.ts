const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });

export function formatInr(v: number | null | undefined): string {
  if (v == null) return '—';
  return inr.format(v);
}

export function formatScore(v: number | null | undefined): string {
  if (v == null) return '—';
  return v.toFixed(2);
}

export function formatAge(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function humanise(s: string): string {
  return s.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}
