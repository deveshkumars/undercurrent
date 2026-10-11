import type { Signal } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function parseDay(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

export function dayNumber(iso: string): number {
  return Math.round(parseDay(iso).getTime() / 86_400_000);
}

export function fmtDate(iso: string | null | undefined, withYear = false): string {
  if (!iso) return "—";
  const d = parseDay(iso);
  const base = `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
  return withYear ? `${base}, ${d.getUTCFullYear()}` : base;
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  return v == null ? "—" : `${v.toFixed(digits)}%`;
}

/** Signed percentage-point change, e.g. "+2.4 pts". */
export function fmtPts(v: number | null | undefined, digits = 1, unit = true): string {
  if (v == null) return "—";
  const s = `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}`;
  return unit ? `${s} pts` : s;
}

export function deltaClass(v: number | null | undefined, threshold = 0.05): "up" | "down" | "flat" {
  if (v == null || Math.abs(v) < threshold) return "flat";
  return v > 0 ? "up" : "down";
}

export function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const today = new Date();
  const t = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((parseDay(iso).getTime() - t) / 86_400_000);
}

export function humanize(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function metricLabel(metric: string): string {
  const known: Record<string, string> = {
    vote_share: "Vote share",
    approval: "Approval",
    favorability: "Favorability",
  };
  return known[metric] ?? humanize(metric);
}

export const SIGNAL_TEXT: Record<Signal, string> = {
  strong: "strong signal",
  clear: "clear signal",
  weak: "weak signal",
  none: "within noise",
  insufficient: "not enough polls",
};

export function isSignificant(signal: Signal): boolean {
  return signal === "strong" || signal === "clear";
}

export function relTime(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Clean axis ticks covering [lo, hi]. */
export function niceTicks(lo: number, hi: number, target = 5): number[] {
  const span = hi - lo || 1;
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= target + 1) ?? 10 * mag;
  const start = Math.ceil(lo / step) * step;
  const ticks = [];
  for (let v = start; v <= hi + 1e-9; v += step) ticks.push(Math.round(v * 100) / 100);
  return ticks;
}

const ID_RE = /\[([0-9a-f]{12})\]/g;

/** Swap bracketed event ids the model left in prose for the event's title. */
export function replaceIds<T>(value: T, titles: Record<string, string>): T {
  if (typeof value === "string") return value.replace(ID_RE, (m, id) => (titles[id] ? `“${titles[id]}”` : m)) as T;
  if (Array.isArray(value)) return value.map((v) => replaceIds(v, titles)) as T;
  if (value && typeof value === "object")
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, replaceIds(v, titles)])) as T;
  return value;
}
