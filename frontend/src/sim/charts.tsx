import { useState, type ReactNode } from "react";
import { useWidth } from "../components/MiniCharts";
import { niceTicks } from "../format";

/** Arms keep a fixed color: control is the neutral baseline, treatments take categorical slots in order. */
export function armColor(index: number): string {
  return index === 0 ? "var(--neutral-mark)" : `var(--series-${Math.min(index, 5)})`;
}

export const PARTY_COLOR: Record<string, string> = {
  democrat: "var(--party-dem)",
  republican: "var(--party-rep)",
  independent: "var(--party-ind)",
  unknown: "var(--neutral-mark)",
};

const signed = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(d)}`;

function roundedBar(x0: number, x1: number, cy: number, h: number): string {
  // 4px rounded data-end, square at the baseline (x0 is the baseline)
  const w = Math.abs(x1 - x0);
  if (w < 0.5) return "";
  const r = Math.min(4, w / 2, h / 2);
  const top = cy - h / 2;
  const bot = cy + h / 2;
  if (x1 >= x0) return `M${x0},${top}H${x1 - r}Q${x1},${top} ${x1},${top + r}V${bot - r}Q${x1},${bot} ${x1 - r},${bot}H${x0}Z`;
  return `M${x0},${top}H${x1 + r}Q${x1},${top} ${x1},${top + r}V${bot - r}Q${x1},${bot} ${x1 + r},${bot}H${x0}Z`;
}

function Tip({ x, y, width, children }: { x: number; y: number; width: number; children: ReactNode }) {
  const left = Math.min(Math.max(0, x + 12), Math.max(0, width - 230));
  return (
    <div className="tooltip" style={{ left, top: Math.max(0, y - 10) }}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------- interval bars

export interface IntervalRow {
  key: string;
  label: string;
  sub?: string;
  est: number | null;
  lo: number | null;
  hi: number | null;
  faded?: boolean;
  note?: string;
}

/** Effects with 95% intervals on a zero-centered axis. Color only when the interval excludes zero, with ▲/▼ so color is never alone. */
export function IntervalBars({ rows, unit = "pts", compact = false }: { rows: IntervalRow[]; unit?: string; compact?: boolean }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<{ row: IntervalRow; x: number; y: number } | null>(null);
  const valid = rows.filter((r) => r.est != null);
  if (!valid.length) return <p className="muted small">No estimates.</p>;
  const labelW = Math.min(compact ? 150 : 210, Math.max(110, width * 0.34));
  const rowH = compact ? 30 : rows.some((r) => r.sub) ? 40 : 32;
  const plotL = labelW + 12;
  const plotR = width - 58;
  const extent = Math.max(1, ...valid.map((r) => Math.max(Math.abs(r.lo ?? r.est!), Math.abs(r.hi ?? r.est!), Math.abs(r.est!)))) * 1.08;
  const x = (v: number) => plotL + ((v + extent) / (2 * extent)) * (plotR - plotL);
  const zero = x(0);
  const height = rows.length * rowH + 22;
  const ticks = niceTicks(-extent, extent, 4);
  return (
    <div ref={ref} className="chart-wrap" onPointerLeave={() => setHover(null)}>
      <svg width={width} height={height} role="img" aria-label="Effects with 95% intervals">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={0} y2={height - 18} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} />
            <text x={x(t)} y={height - 4} textAnchor="middle" className="axis-text">
              {t === 0 ? "0" : signed(t, Number.isInteger(t) ? 0 : 1)}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          const cy = i * rowH + rowH / 2;
          if (r.est == null) {
            return (
              <text key={r.key} x={0} y={cy + 4} className="bar-cat">
                {r.label} <tspan className="axis-text">— no estimate</tspan>
              </text>
            );
          }
          const clear = r.lo != null && r.hi != null && (r.lo > 0 || r.hi < 0);
          const color = !clear ? "var(--neutral-mark)" : r.est > 0 ? "var(--good)" : "var(--bad)";
          const active = hover?.row.key === r.key;
          const tipX = (r.est >= 0 ? x(Math.max(r.hi ?? r.est, r.est)) + 6 : x(Math.min(r.lo ?? r.est, r.est)) - 6);
          return (
            <g
              key={r.key}
              tabIndex={0}
              onPointerMove={(e) => setHover({ row: r, x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })}
              onFocus={() => setHover({ row: r, x: zero, y: cy })}
              onBlur={() => setHover(null)}
              opacity={r.faded ? 0.45 : 1}
            >
              <rect x={0} y={cy - rowH / 2} width={width} height={rowH} fill={active ? "var(--surface-2)" : "transparent"} rx={6} />
              <text x={0} y={r.sub ? cy - 2 : cy + 4} className="bar-cat">
                {r.label.length > 30 ? r.label.slice(0, 29) + "…" : r.label}
              </text>
              {r.sub && (
                <text x={0} y={cy + 13} className="axis-text">
                  {r.sub}
                </text>
              )}
              <path d={roundedBar(zero, x(r.est), cy, compact ? 10 : 12)} fill={color} opacity={clear ? 0.9 : 0.6} />
              {r.lo != null && r.hi != null && (
                <g stroke="var(--ink-2)" strokeWidth={1}>
                  <line x1={x(r.lo)} x2={x(r.hi)} y1={cy} y2={cy} />
                  <line x1={x(r.lo)} x2={x(r.lo)} y1={cy - 5} y2={cy + 5} />
                  <line x1={x(r.hi)} x2={x(r.hi)} y1={cy - 5} y2={cy + 5} />
                </g>
              )}
              <circle cx={x(r.est)} cy={cy} r={4} fill={color} stroke="var(--surface)" strokeWidth={2} />
              <text x={tipX} y={cy + 4} textAnchor={r.est >= 0 ? "start" : "end"} className="bar-label">
                {clear ? (r.est > 0 ? "▲ " : "▼ ") : ""}
                {signed(r.est)}
              </text>
            </g>
          );
        })}
      </svg>
      {hover && (
        <Tip x={hover.x} y={hover.y} width={width}>
          <div className="tt-row">
            <strong>
              {signed(hover.row.est!)} {unit}
            </strong>
          </div>
          <div className="tt-date">{hover.row.label}</div>
          {hover.row.lo != null && hover.row.hi != null && (
            <div className="tiny muted">
              95% interval {signed(hover.row.lo)} to {signed(hover.row.hi)}
            </div>
          )}
          {hover.row.note && <div className="tiny muted">{hover.row.note}</div>}
        </Tip>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- grouped share bars

export interface ShareSeries {
  key: string;
  label: string;
  color: string;
  values: Record<string, number | null | undefined>;
}

/** Shares (0-1) per category, one bar per series, grouped by category. */
export function ShareBars({ categories, series }: { categories: string[]; series: ShareSeries[] }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<{ cat: string; x: number; y: number } | null>(null);
  const labelW = Math.min(160, Math.max(90, width * 0.28));
  const barH = series.length > 3 ? 8 : 11;
  const groupH = series.length * (barH + 2) + 14;
  const plotL = labelW + 8;
  const plotR = width - 46;
  const max = Math.max(0.05, ...series.flatMap((s) => categories.map((c) => s.values[c] ?? 0)));
  const x = (v: number) => plotL + (v / max) * (plotR - plotL);
  const height = categories.length * groupH;
  const labelTips = series.length <= 3;
  return (
    <div ref={ref} className="chart-wrap" onPointerLeave={() => setHover(null)}>
      {series.length > 1 && <Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />}
      <svg width={width} height={height} role="img" aria-label="Answer shares by arm">
        <line x1={plotL} x2={plotL} y1={0} y2={height} stroke="var(--axis)" />
        {categories.map((c, ci) => {
          const top = ci * groupH + 6;
          const active = hover?.cat === c;
          return (
            <g key={c} tabIndex={0} onPointerMove={(e) => setHover({ cat: c, x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY })} onFocus={() => setHover({ cat: c, x: plotL, y: top })} onBlur={() => setHover(null)}>
              <rect x={0} y={top - 4} width={width} height={groupH - 4} fill={active ? "var(--surface-2)" : "transparent"} rx={6} />
              <text x={0} y={top + (series.length * (barH + 2)) / 2 + 3} className="bar-cat">
                {c.length > 22 ? c.slice(0, 21) + "…" : c}
              </text>
              {series.map((s, si) => {
                const v = s.values[c] ?? 0;
                const cy = top + si * (barH + 2) + barH / 2;
                return (
                  <g key={s.key}>
                    <path d={roundedBar(plotL, Math.max(plotL + 1, x(v)), cy, barH)} fill={s.color} />
                    {labelTips && (
                      <text x={x(v) + 5} y={cy + 4} className="bar-label">
                        {Math.round(v * 100)}%
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      {hover && (
        <Tip x={hover.x} y={hover.y} width={width}>
          <div className="tt-date">{hover.cat}</div>
          {series.map((s) => (
            <div key={s.key} className="tt-row">
              <span className="legend-item">
                <span className="key-line" style={{ background: s.color }} />
                {s.label}
              </span>
              <strong>{s.values[hover.cat] == null ? "—" : `${((s.values[hover.cat] ?? 0) * 100).toFixed(1)}%`}</strong>
            </div>
          ))}
        </Tip>
      )}
    </div>
  );
}

export function Legend({ items, line = false }: { items: { label: string; color: string; dashed?: boolean }[]; line?: boolean }) {
  return (
    <div className="legend" style={{ marginBottom: 6 }}>
      {items.map((it) => (
        <span key={it.label} className="legend-item">
          {line ? (
            <span className="key-line" style={{ background: it.dashed ? "transparent" : it.color, borderTop: it.dashed ? `2px dashed ${it.color}` : undefined, height: it.dashed ? 0 : 2 }} />
          ) : (
            <span style={{ width: 10, height: 10, borderRadius: 3, background: it.color, display: "inline-block" }} />
          )}
          {it.label}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- histograms (small multiples)

export function Histograms({ panels, lo, hi }: { panels: { key: string; label: string; color: string; bins: (number | null)[]; mean?: number | null }[]; lo: number; hi: number }) {
  const [ref, width] = useWidth();
  const n = Math.max(1, panels.length);
  const cols = width < 520 ? 1 : Math.min(n, 3);
  const pw = (width - (cols - 1) * 16) / cols;
  const ph = 96;
  const max = Math.max(0.01, ...panels.flatMap((p) => p.bins.map((b) => b ?? 0)));
  return (
    <div ref={ref} style={{ display: "grid", gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, gap: 16 }}>
      {panels.map((p) => {
        const bw = (pw - 8) / p.bins.length;
        const span = hi - lo;
        return (
          <div key={p.key}>
            <div className="small" style={{ fontWeight: 600 }}>
              {p.label}
              {p.mean != null && <span className="muted"> · mean {p.mean.toFixed(1)}</span>}
            </div>
            <svg width={pw} height={ph + 18} role="img" aria-label={`Distribution for ${p.label}`}>
              <line x1={0} x2={pw} y1={ph} y2={ph} stroke="var(--axis)" />
              {p.bins.map((b, i) => {
                const h = ((b ?? 0) / max) * (ph - 6);
                const x0 = 4 + i * bw + 1;
                const w = Math.max(1, bw - 2);
                return (
                  <g key={i}>
                    <path d={`M${x0},${ph}V${ph - h + Math.min(4, h / 2, w / 2)}Q${x0},${ph - h} ${x0 + Math.min(4, w / 2)},${ph - h}H${x0 + w - Math.min(4, w / 2)}Q${x0 + w},${ph - h} ${x0 + w},${ph - h + Math.min(4, h / 2, w / 2)}V${ph}Z`} fill={p.color} opacity={h ? 0.9 : 0} />
                    <title>{`${Math.round(lo + (i * span) / p.bins.length)}–${Math.round(lo + ((i + 1) * span) / p.bins.length)}: ${((b ?? 0) * 100).toFixed(1)}%`}</title>
                  </g>
                );
              })}
              {p.mean != null && <line x1={4 + ((p.mean - lo) / span) * (pw - 8)} x2={4 + ((p.mean - lo) / span) * (pw - 8)} y1={2} y2={ph} stroke="var(--ink)" strokeWidth={1.5} />}
              <text x={2} y={ph + 14} className="axis-text">
                {lo}
              </text>
              <text x={pw - 2} y={ph + 14} textAnchor="end" className="axis-text">
                {hi}
              </text>
            </svg>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- multi-line time series

export interface LineSeries {
  key: string;
  label: string;
  color: string;
  values: (number | null)[];
  dashed?: boolean;
}

export function MultiLine({
  xLabels,
  series,
  markers = [],
  yDomain,
  yFormat = (v: number) => v.toFixed(2),
  height = 190,
  onPick,
  pickLabel,
  zeroLine = false,
}: {
  xLabels: string[];
  series: LineSeries[];
  markers?: { index: number; label: string }[];
  yDomain?: [number, number];
  yFormat?: (v: number) => string;
  height?: number;
  onPick?: (index: number) => void;
  pickLabel?: string;
  zeroLine?: boolean;
}) {
  const [ref, width] = useWidth();
  const [hi, setHi] = useState<number | null>(null);
  const n = xLabels.length;
  if (n < 2) return <p className="muted small">Not enough data yet.</p>;
  const vals = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  let [y0, y1] = yDomain ?? [Math.min(0, ...vals), Math.max(1e-6, ...vals)];
  if (y0 === y1) [y0, y1] = [y0 - 1, y1 + 1];
  const L = 40;
  const R = width - 12;
  const T = 8;
  const B = height - 22;
  const x = (i: number) => L + (i / (n - 1)) * (R - L);
  const y = (v: number) => B - ((v - y0) / (y1 - y0)) * (B - T);
  const ticks = niceTicks(y0, y1, 4);
  const xStep = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((R - L) / 70))));
  const path = (vs: (number | null)[]) => {
    let d = "";
    let pen = false;
    vs.forEach((v, i) => {
      if (v == null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const indexAt = (px: number) => Math.max(0, Math.min(n - 1, Math.round(((px - L) / (R - L)) * (n - 1))));
  function move(e: React.PointerEvent) {
    setHi(indexAt(e.nativeEvent.offsetX));
  }
  return (
    <div ref={ref} className="chart-wrap" onPointerLeave={() => setHi(null)}>
      {series.length > 1 && <Legend line items={series.map((s) => ({ label: s.label, color: s.color, dashed: s.dashed }))} />}
      <svg width={width} height={height} role="img" aria-label="Time series" onPointerMove={move} onClick={(e) => onPick?.(indexAt(e.nativeEvent.offsetX))} style={{ cursor: onPick ? "pointer" : undefined }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={R} y1={y(t)} y2={y(t)} stroke={zeroLine && t === 0 ? "var(--axis)" : "var(--grid)"} />
            <text x={L - 6} y={y(t) + 4} textAnchor="end" className="axis-text">
              {yFormat(t)}
            </text>
          </g>
        ))}
        {xLabels.map((lab, i) =>
          i % xStep === 0 ? (
            <text key={i} x={x(i)} y={height - 6} textAnchor="middle" className="axis-text">
              {lab}
            </text>
          ) : null,
        )}
        {markers.map((m, i) => (
          <g key={i}>
            <line x1={x(m.index)} x2={x(m.index)} y1={T} y2={B} stroke="var(--ink-2)" strokeWidth={1} opacity={0.5} />
            <path d={`M${x(m.index) - 4},${T}L${x(m.index) + 4},${T}L${x(m.index)},${T + 6}Z`} fill="var(--ink-2)" />
            <title>{`${xLabels[m.index]} · ${m.label}`}</title>
          </g>
        ))}
        {series.map((s) => (
          <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dashed ? "5 4" : undefined} />
        ))}
        {series.map((s) => {
          const last = s.values.reduce<number>((acc, v, i) => (v != null ? i : acc), -1);
          return last >= 0 ? <circle key={s.key} cx={x(last)} cy={y(s.values[last]!)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} /> : null;
        })}
        {hi != null && (
          <g>
            <line x1={x(hi)} x2={x(hi)} y1={T} y2={B} stroke="var(--ink-2)" strokeWidth={1} />
            {series.map((s) =>
              s.values[hi] != null ? <circle key={s.key} cx={x(hi)} cy={y(s.values[hi]!)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} /> : null,
            )}
          </g>
        )}
        <rect x={L} y={T} width={R - L} height={B - T} fill="transparent" />
      </svg>
      {hi != null && (
        <Tip x={x(hi)} y={20} width={width}>
          <div className="tt-date">{xLabels[hi]}</div>
          {series.map((s) => (
            <div key={s.key} className="tt-row">
              <span className="legend-item">
                <span className="key-line" style={{ background: s.color }} />
                {s.label}
              </span>
              <strong>{s.values[hi] == null ? "—" : yFormat(s.values[hi]!)}</strong>
            </div>
          ))}
          {markers.filter((m) => m.index === hi).map((m, i) => (
            <div key={i} className="tt-event tiny">
              {m.label}
            </div>
          ))}
          {onPick && <div className="tt-event tiny muted">{pickLabel ?? "Click to select"}</div>}
        </Tip>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- scatter with fit

export function Scatter({
  points,
  slope,
  xLabel,
  yLabel,
}: {
  points: { key: string; label: string; x: number; y: number; strong?: boolean }[];
  slope?: number | null;
  xLabel: string;
  yLabel: string;
}) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<{ key: string; px: number; py: number } | null>(null);
  const height = 260;
  const L = 44;
  const R = width - 12;
  const T = 10;
  const B = height - 34;
  const ext = Math.max(1, ...points.flatMap((p) => [Math.abs(p.x), Math.abs(p.y)])) * 1.15;
  const x = (v: number) => L + ((v + ext) / (2 * ext)) * (R - L);
  const y = (v: number) => B - ((v + ext) / (2 * ext)) * (B - T);
  const ticks = niceTicks(-ext, ext, 4);
  const hp = points.find((p) => p.key === hover?.key);
  return (
    <div ref={ref} className="chart-wrap" onPointerLeave={() => setHover(null)}>
      <Legend line items={[{ label: "Perfect agreement (y = x)", color: "var(--axis)", dashed: true }, ...(slope != null ? [{ label: `Fitted: measured ≈ ${slope.toFixed(2)} × simulated`, color: "var(--series-1)" }] : [])]} />
      <svg width={width} height={height} role="img" aria-label={`${yLabel} versus ${xLabel}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={T} y2={B} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} />
            <line x1={L} x2={R} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} />
            <text x={x(t)} y={B + 14} textAnchor="middle" className="axis-text">
              {signed(t, Number.isInteger(t) ? 0 : 1)}
            </text>
            <text x={L - 6} y={y(t) + 4} textAnchor="end" className="axis-text">
              {signed(t, Number.isInteger(t) ? 0 : 1)}
            </text>
          </g>
        ))}
        <text x={(L + R) / 2} y={height - 4} textAnchor="middle" className="axis-text">
          {xLabel}
        </text>
        <text x={12} y={(T + B) / 2} textAnchor="middle" className="axis-text" transform={`rotate(-90 12 ${(T + B) / 2})`}>
          {yLabel}
        </text>
        <line x1={x(-ext)} y1={y(-ext)} x2={x(ext)} y2={y(ext)} stroke="var(--axis)" strokeWidth={1.5} strokeDasharray="5 4" />
        {slope != null && <line x1={x(-ext)} y1={y(-ext * slope)} x2={x(ext)} y2={y(ext * slope)} stroke="var(--series-1)" strokeWidth={2} />}
        {points.map((p) => (
          <g key={p.key} tabIndex={0} onPointerEnter={() => setHover({ key: p.key, px: x(p.x), py: y(p.y) })} onFocus={() => setHover({ key: p.key, px: x(p.x), py: y(p.y) })} onBlur={() => setHover(null)}>
            <circle cx={x(p.x)} cy={y(p.y)} r={12} fill="transparent" />
            <circle cx={x(p.x)} cy={y(p.y)} r={5} fill={p.strong ? "var(--series-2)" : "var(--neutral-mark)"} stroke="var(--surface)" strokeWidth={2} />
          </g>
        ))}
      </svg>
      {hover && hp && (
        <Tip x={hover.px} y={hover.py} width={width}>
          <div className="tt-date">{hp.label}</div>
          <div className="tt-row">
            <span>Simulated</span>
            <strong>{signed(hp.x)} pts</strong>
          </div>
          <div className="tt-row">
            <span>Measured in polls</span>
            <strong>{signed(hp.y)} pts</strong>
          </div>
        </Tip>
      )}
      <div className="legend tiny" style={{ marginTop: 4 }}>
        <span className="legend-item">
          <span style={{ width: 9, height: 9, borderRadius: 9, background: "var(--series-2)", display: "inline-block" }} />
          clear or strong measured signal
        </span>
        <span className="legend-item">
          <span style={{ width: 9, height: 9, borderRadius: 9, background: "var(--neutral-mark)", display: "inline-block" }} />
          weak or no signal
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- composition: target vs achieved

export function CompositionBars({ title, levels }: { title: string; levels: { label: string; target: number | null; weighted: number; raw: number }[] }) {
  const [ref, width] = useWidth();
  const labelW = Math.min(120, Math.max(80, width * 0.35));
  const rowH = 22;
  const plotL = labelW + 6;
  const plotR = width - 44;
  const max = Math.max(0.05, ...levels.flatMap((l) => [l.weighted, l.target ?? 0, l.raw]));
  const x = (v: number) => plotL + (v / max) * (plotR - plotL);
  return (
    <div ref={ref}>
      <div className="small" style={{ fontWeight: 600, marginBottom: 2 }}>
        {title}
      </div>
      <svg width={width} height={levels.length * rowH + 4} role="img" aria-label={`${title}: weighted share vs target`}>
        {levels.map((l, i) => {
          const cy = i * rowH + rowH / 2;
          return (
            <g key={l.label}>
              <text x={0} y={cy + 4} className="axis-text" style={{ fill: "var(--ink-2)" }}>
                {l.label}
              </text>
              <path d={roundedBar(plotL, Math.max(plotL + 1, x(l.weighted)), cy, 9)} fill="var(--series-1)" />
              {l.target != null && <line x1={x(l.target)} x2={x(l.target)} y1={cy - 8} y2={cy + 8} stroke="var(--ink)" strokeWidth={2} />}
              <text x={x(Math.max(l.weighted, l.target ?? 0)) + 6} y={cy + 4} className="bar-label">
                {Math.round(l.weighted * 100)}%
              </text>
              <title>{`${l.label}: ${(l.weighted * 100).toFixed(1)}% weighted · ${(l.raw * 100).toFixed(1)}% unweighted${l.target != null ? ` · target ${(l.target * 100).toFixed(1)}%` : ""}`}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
