import { useMemo, useState } from "react";
import { api } from "../api";
import { ReportPicker, UsageNote } from "../components/ReportPicker";
import { Card, ErrorNotice, Paragraphs, Working } from "../components/ui";
import { daysUntil, humanize, replaceIds } from "../format";
import type { AnalysisParams, Candidate, RecommendationsReport } from "../types";
import { useReports } from "./useReports";

const IMPACT_CHIP: Record<string, string> = { high: "good", medium: "accent", low: "" };

export function StrategyView({ candidate, params, eventTitles }: { candidate: Candidate; params: AnalysisParams; eventTitles: Record<string, string> }) {
  const { reports, active, setActiveId, add, remove } = useReports<RecommendationsReport>(candidate.id, "recommendations");
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const days = daysUntil(candidate.election_date);
  const output = useMemo(() => (active ? replaceIds(active.output, eventTitles) : null), [active, eventTitles]);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      add(await api.recommendations(candidate.id, { ...params, goal }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <Card
        title="Recommendations"
        sub={`A strategy grounded in what has measurably worked for ${candidate.name}${days != null && days >= 0 ? `, with ${days} days to go` : ""}.`}
      >
        <div className="stack-sm">
          <textarea
            className="input"
            rows={2}
            style={{ minHeight: 60 }}
            placeholder="Optional goal, e.g. “Win back independents without losing the base” or “Recover from the debate”"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          <div className="row" style={{ justifyContent: "space-between" }}>
            <button className="btn primary" onClick={run} disabled={busy}>
              {busy ? "Thinking…" : "Get recommendations"}
            </button>
            <ReportPicker reports={reports} activeId={active?.id ?? null} onPick={setActiveId} onDelete={remove} label={(r) => String(r.params.goal || "General strategy").slice(0, 60)} />
          </div>
          <ErrorNotice error={error} />
        </div>
      </Card>

      {busy && <Working label="Building a strategy from the record. This usually takes 20–60 seconds." />}

      {!busy && active && output && (
        <div className="stack">
          <Card>
            <div className="stack">
              {active.params.goal ? <div className="section-title">Goal: {String(active.params.goal)}</div> : null}
              <Paragraphs text={output.strategic_summary} />
              <UsageNote report={active} />
            </div>
          </Card>

          <div className="grid cols-2-even">
            {output.priorities.map((p, i) => (
              <Card key={i}>
                <div className="stack-sm">
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                    <h3 style={{ fontSize: 16, flex: 1 }}>
                      {i + 1}. {p.title}
                    </h3>
                    <span className={`chip ${IMPACT_CHIP[p.expected_impact]}`}>{p.expected_impact} impact</span>
                  </div>
                  <p className="small secondary">{p.rationale}</p>
                  <ul className="checklist">
                    {p.actions.map((a, j) => (
                      <li key={j}>{a}</li>
                    ))}
                  </ul>
                  <div className="row">
                    {p.target_segments.map((s) => (
                      <span key={s} className="chip accent">
                        {s}
                      </span>
                    ))}
                  </div>
                  {p.evidence_event_ids.length > 0 && (
                    <div className="tiny muted">Evidence: {p.evidence_event_ids.map((id) => eventTitles[id] ?? id).join(" · ")}</div>
                  )}
                </div>
              </Card>
            ))}
          </div>

          <div className="grid cols-2-even">
            <Card title="Amplify">
              <div className="stack-sm">
                {output.amplify.map((m, i) => (
                  <div key={i} className="line-card strength">
                    <strong className="small">{m.message}</strong>
                    <p className="small secondary">{m.evidence}</p>
                  </div>
                ))}
              </div>
            </Card>
            <Card title="Drop or reframe">
              <div className="stack-sm">
                {output.avoid_or_reframe.map((m, i) => (
                  <div key={i} className="line-card risk">
                    <strong className="small">{m.message}</strong>
                    <p className="small secondary">{m.problem}</p>
                    <div className="rewrite">
                      <div className="tiny muted">Reframe</div>
                      {m.reframe}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          <div className="grid cols-2-even">
            <Card title="Formats">
              <div className="stack-sm">
                {output.format_strategy.map((f, i) => (
                  <div key={i} className="small">
                    <strong>{humanize(f.event_type)}</strong>
                    <p className="secondary">{f.advice}</p>
                  </div>
                ))}
              </div>
            </Card>
            <Card title="Next 30 days">
              <ul className="checklist">
                {output.next_30_days.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
              {output.metrics_to_watch.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div className="section-title">Watch</div>
                  <ul className="bullets small secondary">
                    {output.metrics_to_watch.map((m, i) => (
                      <li key={i}>{m}</li>
                    ))}
                  </ul>
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
