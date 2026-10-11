export interface SimRoute {
  parts: string[];
  query: URLSearchParams;
}

export function readSimRoute(hash: string): SimRoute | null {
  const raw = hash.replace(/^#\/?/, "");
  const [path, search = ""] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] !== "sim") return null;
  return { parts: parts.slice(1), query: new URLSearchParams(search) };
}

export function simHref(path = "", query: Record<string, string | null | undefined> = {}): string {
  const qs = Object.entries(query)
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`)
    .join("&");
  return `#/sim${path ? `/${path}` : ""}${qs ? `?${qs}` : ""}`;
}

export function goSim(path = "", query: Record<string, string | null | undefined> = {}) {
  window.location.hash = simHref(path, query).slice(1);
}

export const KIND_LABEL: Record<string, string> = {
  populate: "Persona generation",
  panel: "Message test",
  calibration: "Calibration",
  backtest: "Backtest",
  social: "Social spread",
};

export function pct(v: number | null | undefined, digits = 0): string {
  return v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
}

export function signed(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}`;
}

export function levelLabel(level: string, labels: Record<string, string> = {}): string {
  return labels[level] ?? level.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export const DIM_LABEL: Record<string, string> = {
  party: "Party ID",
  lean: "Partisan lean",
  ideology: "Ideology",
  age_band: "Age",
  gender: "Gender",
  race: "Race / ethnicity",
  education: "Education",
  college: "College degree",
  urbanicity: "Community",
  region: "Region",
  vote_2024: "2024 vote",
  persuadable: "Persuadability",
};

export function dimLabel(dim: string): string {
  if (dim.startsWith("poll: ")) return `Poll segment: ${dim.slice(6)}`;
  return DIM_LABEL[dim] ?? levelLabel(dim);
}
