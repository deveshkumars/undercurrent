import { useLayoutEffect, useRef, useState } from "react";
import { fmtPts, humanize } from "../format";
import type { GroupEffect } from "../types";

export function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(400);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.floor(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/** Horizontal diverging bars from zero with a ±1 SE whisker; status color + sign so color is never alone. */
export function EffectBars({ rows, onHover }: { rows: GroupEffect[]; onHover?: (ids: string[] | null) => void }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<string | null>(null);
  if (!rows.length) return <p className="muted small">No measurable events yet.</p>;
  const labelW = Math.min(150, Math.max(96, width * 0.32));
  const valueW = 64;
  const rowH = 30;
  const barH = 14;
  const plotL = labelW + valueW / 2 + 8;
  const plotR = width - valueW / 2 - 8;
  const extent = Math.max(1, ...rows.map((r) => Math.abs(r.mean_delta) + r.se));
  const x = (v: number) => plotL + ((v + extent) / (2 * extent)) * (plotR - plotL);
  const zero = x(0);
  const height = rows.length * rowH + 8;

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <svg width={width} height={height} role="img" aria-label="Average polling effect by group">
        <line x1={zero} x2={zero} y1={0} y2={height - 4} stroke="var(--axis)" strokeWidth={1} />
        {rows.map((r, i) => {
          const cy = i * rowH + rowH / 2 + 2;
          const v = r.mean_delta;
          const x0 = Math.min(zero, x(v));
          const w = Math.max(2, Math.abs(x(v) - zero));
          const significant = Math.abs(r.z) >= 1.96;
          const color = v >= 0 ? "var(--good)" : "var(--bad)";
          const active = hover === r.label;
          // 4px rounded data-end, square at the baseline
          const rr = Math.min(4, w / 2);
          const path =
            v >= 0
              ? `M${x0},${cy - barH / 2}H${x0 + w - rr}Q${x0 + w},${cy - barH / 2} ${x0 + w},${cy - barH / 2 + rr}V${cy + barH / 2 - rr}Q${x0 + w},${cy + barH / 2} ${x0 + w - rr},${cy + barH / 2}H${x0}Z`
              : `M${x0 + w},${cy - barH / 2}H${x0 + rr}Q${x0},${cy - barH / 2} ${x0},${cy - barH / 2 + rr}V${cy + barH / 2 - rr}Q${x0},${cy + barH / 2} ${x0 + rr},${cy + barH / 2}H${x0 + w}Z`;
          const tipX = v >= 0 ? Math.max(x(v + r.se), x(v)) + 6 : Math.min(x(v - r.se), x(v)) - 6;
          return (
            <g
              key={r.label}
              onPointerEnter={() => {
                setHover(r.label);
                onHover?.(r.event_ids);
              }}
              onPointerLeave={() => {
                setHover(null);
                onHover?.(null);
              }}
            >
              <rect x={0} y={cy - rowH / 2} width={width} height={rowH} fill={active ? "var(--surface-2)" : "transparent"} rx={6} />
              <text x={0} y={cy + 4} className="bar-cat">
                {humanize(r.label).length > 22 ? humanize(r.label).slice(0, 21) + "…" : humanize(r.label)}
              </text>
              <path d={path} fill={color} opacity={significant ? 1 : 0.45} />
              <line x1={x(v - r.se)} x2={x(v + r.se)} y1={cy} y2={cy} stroke="var(--ink-2)" strokeWidth={1} />
              <line x1={x(v - r.se)} x2={x(v - r.se)} y1={cy - 4} y2={cy + 4} stroke="var(--ink-2)" strokeWidth={1} />
              <line x1={x(v + r.se)} x2={x(v + r.se)} y1={cy - 4} y2={cy + 4} stroke="var(--ink-2)" strokeWidth={1} />
              <text x={tipX} y={cy + 4} textAnchor={v >= 0 ? "start" : "end"} className="bar-label">
                {fmtPts(v, 1, false)}
              </text>
              <title>
                {`${humanize(r.label)}: ${fmtPts(v)} average across ${r.count} event${r.count === 1 ? "" : "s"} (±${r.se.toFixed(1)} SE)`}
              </title>
            </g>
          );
        })}
      </svg>
      <div className="tiny muted">Bars: average change after events in each group. Whiskers: ±1 standard error. Faded bars are within noise.</div>
    </div>
  );
}

export function Sparkline({ values, width = 120, height = 32 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * (width - 4) + 2},${height - 3 - ((v - lo) / span) * (height - 6)}`);
  const [lx, ly] = pts[pts.length - 1].split(",").map(Number);
  return (
    <svg width={width} height={height} aria-hidden="true">
      <polyline points={pts.join(" ")} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" opacity={0.9} />
      <circle cx={lx} cy={ly} r={3} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={1.5} />
    </svg>
  );
}

/** Number line showing the statistical prior range, the forecast range and the point estimate. */
export function ForecastRange({ prior, low, high, point }: { prior: [number, number]; low: number; high: number; point: number }) {
  const [ref, width] = useWidth();
  const extent = Math.max(2, Math.ceil(Math.max(...[prior[0], prior[1], low, high].map(Math.abs)) + 0.5));
  const L = 16;
  const R = width - 16;
  const x = (v: number) => L + ((v + extent) / (2 * extent)) * (R - L);
  const ticks = [];
  for (let t = -extent; t <= extent; t += extent > 4 ? 2 : 1) ticks.push(t);
  const color = point > 0.25 ? "var(--good)" : point < -0.25 ? "var(--bad)" : "var(--ink-2)";
  return (
    <div ref={ref}>
      <svg width={width} height={92} role="img" aria-label={`Forecast ${fmtPts(point)}, range ${fmtPts(low)} to ${fmtPts(high)}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={14} y2={70} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} />
            <text x={x(t)} y={86} textAnchor="middle" className="axis-text">
              {t > 0 ? `+${t}` : t}
            </text>
          </g>
        ))}
        <text x={L} y={10} className="axis-text">
          Historical prior (80%)
        </text>
        <rect x={x(prior[0])} y={16} width={Math.max(2, x(prior[1]) - x(prior[0]))} height={10} rx={5} fill="var(--neutral-mark)" opacity={0.45} />
        <text x={L} y={44} className="axis-text">
          Forecast (80%)
        </text>
        <rect x={x(low)} y={50} width={Math.max(2, x(high) - x(low))} height={12} rx={6} fill={color} opacity={0.28} />
        <circle cx={x(point)} cy={56} r={6} fill={color} stroke="var(--surface)" strokeWidth={2} />
      </svg>
    </div>
  );
}
