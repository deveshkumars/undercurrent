import { useEffect, useMemo, useRef, useState } from "react";
import { ChartLegend, PollChart } from "../components/PollChart";
import { EffectBars, Sparkline } from "../components/MiniCharts";
import { Card, Delta, ImpactBadge } from "../components/ui";
import { fmtDate, fmtPct, fmtPts, humanize, metricLabel, SIGNAL_TEXT } from "../format";
import type { Analysis, Candidate, ScoredEvent } from "../types";

export function Overview({ candidate, analysis, onGoToData }: { candidate: Candidate; analysis: Analysis; onGoToData: () => void }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showPolls, setShowPolls] = useState(true);
  const [tableView, setTableView] = useState(false);
  const [sort, setSort] = useState<"date" | "impact">("impact");
  const [groupBy, setGroupBy] = useState<"themes" | "event_types">("themes");
  const s = analysis.stats;
  const hasOpp = analysis.trend.some((t) => t.opp != null);
  const oppName = candidate.opponent_name || "Opponent";

  const sortedEvents = useMemo(() => {
    const evs = [...analysis.events];
    if (sort === "date") return evs.sort((a, b) => b.date.localeCompare(a.date));
    const score = (e: ScoredEvent) => (e.impact.signal === "insufficient" ? -1 : Math.abs(e.impact.z ?? 0));
    return evs.sort((a, b) => score(b) - score(a));
  }, [analysis.events, sort]);

  if (!s.poll_count) {
    return (
      <Card>
        <div className="empty">
          <h2>No polls for this view yet</h2>
          <p>
            Add polls for <strong>{metricLabel(analysis.metric)}</strong> · <strong>{analysis.segment}</strong>, or pick another metric or segment above.
          </p>
          <div className="row" style={{ justifyContent: "center", marginTop: 16 }}>
            <button className="btn primary" onClick={onGoToData}>
              Add polls and events
            </button>
          </div>
        </div>
      </Card>
    );
  }

  const spark = analysis.trend.slice(-60).map((t) => t.value);

  return (
    <div className="stack">
      <div className="tiles" style={{ marginBottom: 0 }}>
        <div className="tile">
          <div className="tile-label">{metricLabel(analysis.metric)} average</div>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
            <div className="tile-value hero">{fmtPct(s.latest)}</div>
            <Sparkline values={spark} width={96} height={34} />
          </div>
          <div className="tile-foot">
            ±{((s.latest_se ?? 0) * 1.96).toFixed(1)} · as of {fmtDate(s.latest_date)}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Last 30 days</div>
          <div className="tile-value">
            <Delta value={s.change_30d} />
          </div>
          <div className="tile-foot">
            7 days: <Delta value={s.change_7d} />
          </div>
        </div>
        {s.margin != null && (
          <div className="tile">
            <div className="tile-label">Margin vs {oppName}</div>
            <div className="tile-value">
              <Delta value={s.margin} />
            </div>
            <div className="tile-foot">
              30-day shift <Delta value={s.margin_change_30d} />
            </div>
          </div>
        )}
        <div className="tile">
          <div className="tile-label">Typical 2-week swing</div>
          <div className="tile-value">±{s.volatility_14d?.toFixed(1) ?? "—"}</div>
          <div className="tile-foot">smaller event effects are hard to see</div>
        </div>
        <div className="tile">
          <div className="tile-label">Polls</div>
          <div className="tile-value">{s.poll_count}</div>
          <div className="tile-foot">
            {s.pollster_count} pollsters · since {fmtDate(s.first_date)}
          </div>
        </div>
      </div>

      <Card
        title={`${metricLabel(analysis.metric)} · ${analysis.segment}`}
        sub="House-effect-adjusted polling average with a 95% band. Markers show campaign events and whether polls moved after them."
        actions={
          <>
            <label className="row small secondary" style={{ gap: 6 }}>
              <input type="checkbox" checked={showPolls} onChange={(e) => setShowPolls(e.target.checked)} /> Individual polls
            </label>
            <div className="seg-toggle" role="group" aria-label="View">
              <button aria-pressed={!tableView} onClick={() => setTableView(false)}>
                Chart
              </button>
              <button aria-pressed={tableView} onClick={() => setTableView(true)}>
                Table
              </button>
            </div>
          </>
        }
      >
        {tableView ? (
          <TrendTable analysis={analysis} candidateName={candidate.name} oppName={oppName} />
        ) : (
          <div className="stack-sm">
            <ChartLegend candidateName={candidate.name} opponentName={oppName} hasOpp={hasOpp} />
            <PollChart
              trend={analysis.trend}
              polls={analysis.polls}
              events={analysis.events}
              windowDays={analysis.window_days}
              candidateName={candidate.name}
              opponentName={oppName}
              selectedId={selectedId}
              onSelect={setSelectedId}
              showPolls={showPolls}
            />
            {selectedId && (
              <div className="tiny muted">
                Shaded: {analysis.window_days} days before and after the selected event. Horizontal marks: the average of polls in each window.
              </div>
            )}
          </div>
        )}
      </Card>

      <div className="grid cols-2">
        <Card
          title="Events lined up with the polls"
          sub={`Change in the average from ${analysis.window_days} days before to ${analysis.window_days} days after each event.`}
          actions={
            <div className="seg-toggle" role="group" aria-label="Sort events">
              <button aria-pressed={sort === "impact"} onClick={() => setSort("impact")}>
                Biggest signal
              </button>
              <button aria-pressed={sort === "date"} onClick={() => setSort("date")}>
                Newest
              </button>
            </div>
          }
        >
          {sortedEvents.length === 0 ? (
            <p className="muted small">
              No events yet.{" "}
              <button className="btn sm" onClick={onGoToData}>
                Add events
              </button>
            </p>
          ) : (
            <EventImpactList events={sortedEvents} selectedId={selectedId} onSelect={setSelectedId} />
          )}
        </Card>

        <div className="stack">
          <Card
            title="What moves the numbers"
            sub="Average change after events, pooled by topic or format."
            actions={
              <div className="seg-toggle" role="group" aria-label="Group by">
                <button aria-pressed={groupBy === "themes"} onClick={() => setGroupBy("themes")}>
                  Topic
                </button>
                <button aria-pressed={groupBy === "event_types"} onClick={() => setGroupBy("event_types")}>
                  Format
                </button>
              </div>
            }
          >
            <EffectBars rows={analysis[groupBy]} />
          </Card>

          {analysis.house_effects.length > 0 && (
            <Card title="Pollster house effects" sub="Average lean of each pollster relative to the others; removed before averaging.">
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Pollster</th>
                      <th className="num">Lean</th>
                      <th className="num">Polls</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysis.house_effects.map((h) => (
                      <tr key={h.pollster}>
                        <td>{h.pollster}</td>
                        <td className="num">{fmtPts(h.effect, 1, false)}</td>
                        <td className="num">{h.n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function EventImpactList({ events, selectedId, onSelect }: { events: ScoredEvent[]; selectedId: string | null; onSelect: (id: string | null) => void }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  useEffect(() => {
    if (selectedId) refs.current[selectedId]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedId]);

  return (
    <div className="event-list">
      {events.map((ev) => {
        const open = ev.id === selectedId;
        return (
          <div key={ev.id}>
            <button
              className="event-row"
              aria-expanded={open}
              ref={(el) => {
                refs.current[ev.id] = el;
              }}
              onClick={() => onSelect(open ? null : ev.id)}
            >
              <div className="event-date">{fmtDate(ev.date)}</div>
              <div>
                <div className="event-title">{ev.title}</div>
                <div className="event-meta">
                  <span className="chip">{humanize(ev.type)}</span>
                  {ev.topics.slice(0, 3).map((t) => (
                    <span key={t} className="chip">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
              <div className="event-impact">
                <ImpactBadge delta={ev.impact.delta} signal={ev.impact.signal} />
                <div className="signal">{SIGNAL_TEXT[ev.impact.signal]}</div>
              </div>
            </button>
            {open && <EventDetail ev={ev} />}
          </div>
        );
      })}
    </div>
  );
}

function EventDetail({ ev }: { ev: ScoredEvent }) {
  const imp = ev.impact;
  const segs = Object.entries(ev.segment_impacts);
  return (
    <div className="event-detail stack-sm">
      {ev.summary && <p className="secondary">{ev.summary}</p>}
      {ev.content && <div className="quote">{ev.content.length > 700 ? ev.content.slice(0, 700) + "…" : ev.content}</div>}
      <dl className="kv">
        <dt>Before → after</dt>
        <dd className="num">
          {imp.pre != null ? `${fmtPct(imp.pre)} → ${fmtPct(imp.post)}` : "—"} ({imp.n_pre} polls before, {imp.n_post} after)
        </dd>
        <dt>Change</dt>
        <dd className="num">
          {fmtPts(imp.delta)} ± {imp.se != null ? (imp.se * 1.96).toFixed(1) : "—"} (z = {imp.z?.toFixed(2) ?? "—"})
        </dd>
        {(ev.venue || ev.audience) && (
          <>
            <dt>Where / who</dt>
            <dd>{[ev.venue, ev.audience].filter(Boolean).join(" · ")}</dd>
          </>
        )}
        {ev.tone && (
          <>
            <dt>Tone</dt>
            <dd>{ev.tone}</dd>
          </>
        )}
      </dl>
      {segs.length > 0 && (
        <div>
          <div className="tiny muted" style={{ marginBottom: 4 }}>
            By segment
          </div>
          <div className="row">
            {segs.map(([seg, v]) => (
              <span key={seg} className="chip" title={SIGNAL_TEXT[v.signal]}>
                {seg} <Delta value={v.delta} unit={false} />
              </span>
            ))}
          </div>
        </div>
      )}
      {ev.overlaps.length > 0 && (
        <div className="notice warn tiny">
          Shares its window with {ev.overlaps.map((o) => `“${o.title}” (${fmtDate(o.date)})`).join(", ")}, so credit for the movement is ambiguous.
        </div>
      )}
    </div>
  );
}

function TrendTable({ analysis, candidateName, oppName }: { analysis: Analysis; candidateName: string; oppName: string }) {
  const rows = analysis.trend.filter((_, i, arr) => i % 7 === 0 || i === arr.length - 1).reverse();
  const hasOpp = rows.some((r) => r.opp != null);
  return (
    <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
      <table className="data">
        <thead>
          <tr>
            <th>Week of</th>
            <th className="num">{candidateName}</th>
            <th className="num">95% band</th>
            {hasOpp && <th className="num">{oppName}</th>}
            {hasOpp && <th className="num">Margin</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.date}>
              <td>{fmtDate(r.date, true)}</td>
              <td className="num">{fmtPct(r.value)}</td>
              <td className="num">
                {r.lo.toFixed(1)}–{r.hi.toFixed(1)}
              </td>
              {hasOpp && <td className="num">{fmtPct(r.opp)}</td>}
              {hasOpp && <td className="num">{r.opp != null ? fmtPts(r.value - r.opp, 1, false) : "—"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
