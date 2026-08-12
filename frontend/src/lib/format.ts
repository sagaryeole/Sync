/**
 * Display formatters.
 *
 * Every function here takes untrusted network data and MUST NOT throw. A
 * `null` price, a `NaN` from a divide-by-zero metric, or an `Infinity` from a
 * profit factor with no losses used to reach `.toFixed()` directly in the
 * components and take down the whole page — React unmounts the tree on a
 * render throw, so one bad field white-screened the entire terminal.
 *
 * The rule: anything not a finite number renders as EM_DASH. Callers never
 * need to null-check before formatting.
 */

export const EM_DASH = '—';

/** True only for a real, finite number. Rejects null/undefined/NaN/Infinity. */
function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function fmtUsd(value: unknown, decimals = 2): string {
  if (!isFiniteNumber(value)) return EM_DASH;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function fmtNum(value: unknown, decimals = 2): string {
  if (!isFiniteNumber(value)) return EM_DASH;
  return value.toFixed(decimals);
}

export function fmtPct(value: unknown, decimals = 2): string {
  if (!isFiniteNumber(value)) return EM_DASH;
  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}%`;
}

/** For ratios stored as fractions (0.42) that display as percentages (42%). */
export function fmtRatioPct(value: unknown, decimals = 1): string {
  if (!isFiniteNumber(value)) return EM_DASH;
  return `${(value * 100).toFixed(decimals)}%`;
}

export function fmtQty(value: unknown, decimals = 6): string {
  if (!isFiniteNumber(value)) return EM_DASH;
  return value.toFixed(decimals);
}

export function fmtCompact(value: unknown): string {
  if (!isFiniteNumber(value)) return EM_DASH;
  return new Intl.NumberFormat('en-US', {
    notation: 'compact',
    compactDisplay: 'short',
    maximumFractionDigits: 2,
  }).format(value);
}

export function fmtDateTime(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return EM_DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EM_DASH;
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function fmtTime(iso: unknown): string {
  if (typeof iso !== 'string' || !iso) return EM_DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EM_DASH;
  return d.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/** Humanised duration from seconds: 45s, 12m 30s, 3h 05m. */
export function fmtDuration(seconds: unknown): string {
  if (!isFiniteNumber(seconds) || seconds < 0) return EM_DASH;
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`;
}

/**
 * Tailwind text colour class for a signed value. Neutral (not green) for
 * missing data, so an unknown value never reads as a gain.
 */
export function signClass(value: unknown): string {
  if (!isFiniteNumber(value) || value === 0) return 'text-slate-400';
  return value > 0 ? 'text-emerald-400' : 'text-rose-400';
}
