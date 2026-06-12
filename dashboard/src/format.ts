// Central formatting helpers so every monetary amount reads unambiguously as
// money (with its unit) and percentages/prices look consistent across the app.
//
// NOTE: the bot trades USDT pairs, so amounts are in USDT (≈ USD), NOT euro.
// Labelling them explicitly avoids the "is this € or $?" confusion.

export const QUOTE = "USDT";

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return NaN;
  return typeof value === "number" ? value : parseFloat(value);
}

const groups = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** A monetary amount with its unit, e.g. "1,234.56 USDT". */
export function money(value: string | number | null | undefined): string {
  const n = toNum(value);
  if (!Number.isFinite(n)) return `— ${QUOTE}`;
  return `${groups.format(n)} ${QUOTE}`;
}

/** A monetary amount with an explicit +/- sign (for PnL). */
export function signedMoney(value: string | number | null | undefined): string {
  const n = toNum(value);
  if (!Number.isFinite(n)) return `— ${QUOTE}`;
  const sign = n > 0 ? "+" : "";
  return `${sign}${groups.format(n)} ${QUOTE}`;
}

/** A fraction (e.g. "0.0345") rendered as a percentage ("3.45%"). */
export function pct(value: string | number | null | undefined): string {
  const n = toNum(value);
  if (!Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

/** An already-percent number rendered as "12.3%". */
export function pctRaw(value: number | null | undefined, dp = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value.toFixed(dp)}%`;
}

/** A price/quantity with adaptive precision (small coins need more decimals). */
export function price(value: string | number | null | undefined): string {
  const n = toNum(value);
  if (!Number.isFinite(n)) return "—";
  const dp = n >= 1000 ? 2 : n >= 1 ? 4 : n >= 0.01 ? 6 : 8;
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: dp });
}

/** Sign class for colouring ("pos" / "neg" / ""). */
export function cls(value: string | number | null | undefined): string {
  const n = toNum(value);
  if (!Number.isFinite(n) || n === 0) return "";
  return n > 0 ? "pos" : "neg";
}

/** Humanise a number of seconds into "3m ago" / "2h ago". */
export function ago(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

/** Humanise a holding-time duration in seconds into "1h 23m". */
export function holdTime(seconds: number | null | undefined): string {
  if (!seconds || !Number.isFinite(seconds)) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

/** Short local time, e.g. "14:05". */
export function clock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
