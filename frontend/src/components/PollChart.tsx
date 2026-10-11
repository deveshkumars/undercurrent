import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { dayNumber, fmtDate, fmtPct, fmtPts, isSignificant, niceTicks, SIGNAL_TEXT } from "../format";
import type { AnalysisPoll, ScoredEvent, TrendPoint } from "../types";

interface Props {
  trend: TrendPoint[];
  polls: AnalysisPoll[];
  events: ScoredEvent[];
  windowDays: number;
  candidateName: string;
  opponentName: string;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  showPolls: boolean;
  height?: number;
}

const M = { top: 30, right: 60, bottom: 28, left: 36 };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(800);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.floor(entry.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

function linePath(points: [number, number][]): string {
  return points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
}

function bandPath(upper: [number, number][], lower: [number, number][]): string {
  if (!upper.length) return "";
  return linePath(upper) + lower.reverse().map(([x, y]) => `L${x.toFixed(1)},${y.toFixed(1)}`).join("") + "Z";
}

function eventKind(ev: ScoredEvent): "up" | "down" | "weak-up" | "weak-down" | "flat" {
  const { delta, signal } = ev.impact;
  if (delta == null || signal === "insufficient" || signal === "none") return "flat";
  if (isSignificant(signal)) return delta > 0 ? "up" : "down";
  return delta > 0 ? "weak-up" : "weak-down";
}

export function EventGlyph({ kind, x, y, size = 6 }: { kind: ReturnType<typeof eventKind>; x: number; y: number; size?: number }) {
  if (kind === "flat") return <circle cx={x} cy={y} r={size * 0.62} fill="var(--neutral-mark)" stroke="var(--surface)" strokeWidth={2} />;
  const up = kind === "up" || kind === "weak-up";
  const color = up ? "var(--good)" : "var(--bad)";
  const hollow = kind.startsWith("weak");
  const s = size;
  const d = up ? `M${x},${y - s}L${x + s},${y + s * 0.75}L${x - s},${y + s * 0.75}Z` : `M${x},${y + s}L${x + s},${y - s * 0.75}L${x - s},${y - s * 0.75}Z`;
  return <path d={d} fill={hollow ? "var(--surface)" : color} stroke={hollow ? color : "var(--surface)"} strokeWidth={hollow ? 1.75 : 1.5} strokeLinejoin="round" />;
}

export function PollChart({ trend, polls, events, windowDays, candidateName, opponentName, selectedId, onSelect, showPolls, height = 360 }: Props) {
  const [wrapRef, width] = useWidth<HTMLDivElement>();
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [hoverEvent, setHoverEvent] = useState<string | null>(null);
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);

  const hasOpp = trend.some((t) => t.opp != null);
  const innerW = width - M.left - M.right;
  const innerH = height - M.top - M.bottom;

  const geo = useMemo(() => {
    const d0 = dayNumber(trend[0].date);
    const d1 = Math.max(dayNumber(trend[trend.length - 1].date), d0 + 1);
    const vals: number[] = [];
    for (const t of trend) {
      vals.push(t.lo, t.hi);
      if (t.opp_lo != null && t.opp_hi != null) vals.push(t.opp_lo, t.opp_hi);
    }
    if (showPolls)
      for (const p of polls) {
        vals.push(p.adj_value);
        if (p.adj_opponent_value != null) vals.push(p.adj_opponent_value);
      }
    const lo = Math.floor(Math.min(...vals) - 0.5);
    const hi = Math.ceil(Math.max(...vals) + 0.5);
    const yTicks = niceTicks(lo, hi, 5);
    const yLo = Math.min(lo, yTicks[0]);
    const yHi = Math.max(hi, yTicks[yTicks.length - 1]);
    const x = (day: number) => M.left + ((day - d0) / (d1 - d0)) * innerW;
    const y = (v: number) => M.top + (1 - (v - yLo) / (yHi - yLo)) * innerH;
    const months: { x: number; label: string }[] = [];
    const start = new Date(trend[0].date + "T00:00:00Z");
    const cursor = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + (start.getUTCDate() > 1 ? 1 : 0), 1));
    while (cursor.getTime() / 86_400_000 <= d1) {
      const day = Math.round(cursor.getTime() / 86_400_000);
      months.push({ x: x(day), label: MONTHS[cursor.getUTCMonth()] });
      cursor.setUTCMonth(cursor.getUTCMonth() + 1);
    }
    return { d0, d1, x, y, yTicks, months };
  }, [trend, polls, showPolls, innerW, innerH]);

  const { x, y, d0, d1 } = geo;

  const candPts = trend.map((t) => [x(dayNumber(t.date)), y(t.value)] as [number, number]);
  const candHi = trend.map((t) => [x(dayNumber(t.date)), y(t.hi)] as [number, number]);
  const candLo = trend.map((t) => [x(dayNumber(t.date)), y(t.lo)] as [number, number]);
  const oppRows = trend.filter((t) => t.opp != null);
  const oppPts = oppRows.map((t) => [x(dayNumber(t.date)), y(t.opp!)] as [number, number]);
  const oppHi = oppRows.map((t) => [x(dayNumber(t.date)), y(t.opp_hi!)] as [number, number]);
  const oppLo = oppRows.map((t) => [x(dayNumber(t.date)), y(t.opp_lo!)] as [number, number]);

  const visibleEvents = events.filter((e) => {
    const d = dayNumber(e.date);
    return d >= d0 && d <= d1;
  });
  const selected = visibleEvents.find((e) => e.id === selectedId) ?? null;

  // End labels: nudge apart when the two lines finish close together, with a leader back to the line.
  const last = trend[trend.length - 1];
  const endLabels: { y: number; lineY: number; text: string; color: string }[] = [{ y: y(last.value), lineY: y(last.value), text: fmtPct(last.value), color: "var(--series-1)" }];
  if (last.opp != null) endLabels.push({ y: y(last.opp), lineY: y(last.opp), text: fmtPct(last.opp), color: "var(--series-2)" });
  if (endLabels.length === 2 && Math.abs(endLabels[0].y - endLabels[1].y) < 16) {
    const mid = (endLabels[0].y + endLabels[1].y) / 2;
    const [a, b] = endLabels[0].y <= endLabels[1].y ? [endLabels[0], endLabels[1]] : [endLabels[1], endLabels[0]];
    a.y = mid - 8;
    b.y = mid + 8;
  }

  const hovered = hoverIdx != null ? trend[hoverIdx] : null;
  const hoveredDay = hovered ? dayNumber(hovered.date) : null;
  const eventsNearHover = hoveredDay != null ? visibleEvents.filter((e) => Math.abs(dayNumber(e.date) - hoveredDay) <= 1) : [];
  const hoverEv = visibleEvents.find((e) => e.id === hoverEvent) ?? null;

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const day = d0 + ((px - M.left) / innerW) * (d1 - d0);
    const idx = Math.max(0, Math.min(trend.length - 1, Math.round(day - d0)));
    // trend is daily but may skip days; find nearest by date
    let best = idx;
    let bestGap = Infinity;
    for (let i = Math.max(0, idx - 5); i < Math.min(trend.length, idx + 6); i++) {
      const gap = Math.abs(dayNumber(trend[i].date) - day);
      if (gap < bestGap) {
        best = i;
        bestGap = gap;
      }
    }
    setHoverIdx(best);
    setPointer({ x: px, y: e.clientY - rect.top });
  }

  const tooltipLeft = pointer ? (pointer.x > width - 220 ? pointer.x - 196 : pointer.x + 14) : 0;

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg width={width} height={height} role="img" aria-label={`Polling average for ${candidateName}${hasOpp ? ` and ${opponentName}` : ""} with campaign events`}>
        {/* selected event: before/after windows and their means */}
        {selected && (() => {
          const ed = dayNumber(selected.date);
          const xa = x(Math.max(d0, ed - windowDays));
          const xe = x(ed);
          const xb = x(Math.min(d1, ed + windowDays));
          const imp = selected.impact;
          return (
            <g>
              <rect x={xa} y={M.top} width={Math.max(0, xe - xa)} height={innerH} fill="var(--window-wash)" />
              <rect x={xe} y={M.top} width={Math.max(0, xb - xe)} height={innerH} fill="var(--window-wash)" />
              <text x={(xa + xe) / 2} y={M.top + 12} textAnchor="middle" className="axis-text">before</text>
              <text x={(xe + xb) / 2} y={M.top + 12} textAnchor="middle" className="axis-text">after</text>
              {imp.pre != null && <line x1={xa} x2={xe} y1={y(imp.pre)} y2={y(imp.pre)} stroke="var(--ink-2)" strokeWidth={2} strokeLinecap="round" />}
              {imp.post != null && <line x1={xe} x2={xb} y1={y(imp.post)} y2={y(imp.post)} stroke="var(--ink)" strokeWidth={2} strokeLinecap="round" />}
            </g>
          );
        })()}

        {/* grid + y axis */}
        {geo.yTicks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={M.left + innerW} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={M.left - 8} y={y(t) + 4} textAnchor="end" className="axis-text">
              {t}
            </text>
          </g>
        ))}
        <line x1={M.left} x2={M.left + innerW} y1={M.top + innerH} y2={M.top + innerH} stroke="var(--axis)" strokeWidth={1} />
        {geo.months.map((m, i) => (
          <text key={i} x={m.x} y={height - 8} textAnchor="middle" className="axis-text">
            {m.label}
          </text>
        ))}

        {/* event rules */}
        {visibleEvents.map((ev) => {
          const ex = x(dayNumber(ev.date));
          const active = ev.id === selectedId || ev.id === hoverEvent;
          return <line key={ev.id} x1={ex} x2={ex} y1={M.top - 8} y2={M.top + innerH} stroke={active ? "var(--ink-2)" : "var(--grid)"} strokeWidth={1} />;
        })}

        {/* uncertainty bands */}
        <path d={bandPath(candHi, candLo)} fill="var(--band-1)" />
        {hasOpp && <path d={bandPath(oppHi, oppLo)} fill="var(--band-2)" />}

        {/* individual polls */}
        {showPolls && (
          <g>
            {hasOpp &&
              polls.map((p) =>
                p.adj_opponent_value == null ? null : (
                  <circle key={`o${p.id}`} cx={x(dayNumber(p.date))} cy={y(p.adj_opponent_value)} r={3.5} fill="var(--series-2)" opacity={0.28} />
                ),
              )}
            {polls.map((p) => (
              <circle key={p.id} cx={x(dayNumber(p.date))} cy={y(p.adj_value)} r={3.5} fill="var(--series-1)" opacity={0.3} />
            ))}
          </g>
        )}

        {/* averages */}
        {hasOpp && <path d={linePath(oppPts)} fill="none" stroke="var(--series-2)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
        <path d={linePath(candPts)} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {/* end markers + labels */}
        <circle cx={candPts[candPts.length - 1][0]} cy={candPts[candPts.length - 1][1]} r={4} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
        {hasOpp && oppPts.length > 0 && <circle cx={oppPts[oppPts.length - 1][0]} cy={oppPts[oppPts.length - 1][1]} r={4} fill="var(--series-2)" stroke="var(--surface)" strokeWidth={2} />}
        {endLabels.map((l, i) => (
          <g key={i}>
            {Math.abs(l.y - l.lineY) > 1 && <line x1={M.left + innerW + 5} x2={M.left + innerW + 9} y1={l.lineY} y2={l.y} stroke="var(--axis)" />}
            <text x={M.left + innerW + 11} y={l.y + 4} className="end-label">
              {l.text}
            </text>
          </g>
        ))}

        {/* crosshair */}
        {hovered && (
          <g pointerEvents="none">
            <line x1={x(dayNumber(hovered.date))} x2={x(dayNumber(hovered.date))} y1={M.top} y2={M.top + innerH} stroke="var(--ink-2)" strokeWidth={1} />
            <circle cx={x(dayNumber(hovered.date))} cy={y(hovered.value)} r={4} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
            {hovered.opp != null && <circle cx={x(dayNumber(hovered.date))} cy={y(hovered.opp)} r={4} fill="var(--series-2)" stroke="var(--surface)" strokeWidth={2} />}
          </g>
        )}

        <rect
          x={M.left}
          y={M.top}
          width={innerW}
          height={innerH}
          fill="transparent"
          onPointerMove={onMove}
          onPointerLeave={() => {
            setHoverIdx(null);
            setPointer(null);
          }}
          onClick={() => onSelect(eventsNearHover[0]?.id ?? null)}
        />

        {/* event markers (on top so they stay clickable) */}
        {visibleEvents.map((ev) => {
          const ex = x(dayNumber(ev.date));
          const kind = eventKind(ev);
          const active = ev.id === selectedId;
          return (
            <g
              key={ev.id}
              role="button"
              tabIndex={0}
              aria-label={`${ev.title}, ${fmtDate(ev.date)}: ${fmtPts(ev.impact.delta)} (${SIGNAL_TEXT[ev.impact.signal]})`}
              aria-pressed={active}
              style={{ cursor: "pointer" }}
              onPointerEnter={(e) => {
                setHoverEvent(ev.id);
                const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
                setPointer({ x: e.clientX - rect.left, y: e.clientY - rect.top });
                setHoverIdx(null);
              }}
              onPointerLeave={() => setHoverEvent(null)}
              onFocus={() => {
                setHoverEvent(ev.id);
                setPointer({ x: ex, y: M.top });
              }}
              onBlur={() => setHoverEvent(null)}
              onClick={() => onSelect(active ? null : ev.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(active ? null : ev.id);
                }
              }}
            >
              <rect x={ex - 12} y={M.top - 26} width={24} height={24} fill="transparent" />
              {active && <circle cx={ex} cy={M.top - 14} r={10} fill="var(--accent-wash)" stroke="var(--accent)" strokeWidth={1} />}
              <EventGlyph kind={kind} x={ex} y={M.top - 14} />
            </g>
          );
        })}
      </svg>

      {pointer && (hovered || hoverEv) && (
        <div className="tooltip" style={{ left: tooltipLeft, top: Math.max(0, pointer.y - 10) }}>
          {hoverEv ? (
            <EventTooltip ev={hoverEv} />
          ) : hovered ? (
            <>
              <div className="tt-date">{fmtDate(hovered.date, true)}</div>
              <div className="tt-row">
                <span className="row" style={{ gap: 6 }}>
                  <span className="key-line" style={{ background: "var(--series-1)" }} />
                  <span className="secondary">{candidateName}</span>
                </span>
                <strong>{fmtPct(hovered.value)}</strong>
              </div>
              {hovered.opp != null && (
                <div className="tt-row">
                  <span className="row" style={{ gap: 6 }}>
                    <span className="key-line" style={{ background: "var(--series-2)" }} />
                    <span className="secondary">{opponentName}</span>
                  </span>
                  <strong>{fmtPct(hovered.opp)}</strong>
                </div>
              )}
              <div className="tiny muted" style={{ marginTop: 2 }}>
                95% band {hovered.lo.toFixed(1)}–{hovered.hi.toFixed(1)}
              </div>
              {eventsNearHover.map((ev) => (
                <div key={ev.id} className="tt-event">
                  <EventTooltip ev={ev} compact />
                </div>
              ))}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

function EventTooltip({ ev, compact }: { ev: ScoredEvent; compact?: boolean }) {
  return (
    <div>
      {!compact && <div className="tt-date">{fmtDate(ev.date, true)}</div>}
      <div style={{ fontWeight: 600, marginBottom: 2 }}>{ev.title}</div>
      <div className="tt-row">
        <span className="secondary">{SIGNAL_TEXT[ev.impact.signal]}</span>
        <strong>{fmtPts(ev.impact.delta)}</strong>
      </div>
      {!compact && <div className="tiny muted">Click to show the before/after windows</div>}
    </div>
  );
}

export function ChartLegend({ candidateName, opponentName, hasOpp }: { candidateName: string; opponentName: string; hasOpp: boolean }) {
  return (
    <div className="legend" aria-hidden="false">
      <span className="legend-item">
        <span className="key-line" style={{ background: "var(--series-1)" }} />
        {candidateName}
      </span>
      {hasOpp && (
        <span className="legend-item">
          <span className="key-line" style={{ background: "var(--series-2)" }} />
          {opponentName}
        </span>
      )}
      <span className="legend-item">
        <svg width="14" height="14" aria-hidden="true">
          <EventGlyph kind="up" x={7} y={7} size={5} />
        </svg>
        gain
      </span>
      <span className="legend-item">
        <svg width="14" height="14" aria-hidden="true">
          <EventGlyph kind="down" x={7} y={7} size={5} />
        </svg>
        loss
      </span>
      <span className="legend-item">
        <svg width="14" height="14" aria-hidden="true">
          <EventGlyph kind="weak-up" x={7} y={7} size={5} />
        </svg>
        weak signal
      </span>
      <span className="legend-item">
        <svg width="14" height="14" aria-hidden="true">
          <EventGlyph kind="flat" x={7} y={7} size={5} />
        </svg>
        within noise
      </span>
    </div>
  );
}
