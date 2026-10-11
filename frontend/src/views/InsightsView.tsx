import { useMemo, useState } from "react";
import { api } from "../api";
import { ReportPicker, UsageNote } from "../components/ReportPicker";
import { Card, Delta, ErrorNotice, Paragraphs, Working } from "../components/ui";
import { metricLabel, replaceIds } from "../format";
import type { AnalysisParams, Candidate, InsightsReport } from "../types";
import { useReports } from "./useReports";

const VERDICT_CHIP: Record<string, string> = { helps: "good", hurts: "bad", neutral: "", unclear: "warn", mixed: "warn" };

export function InsightsView({ candidate, params, eventTitles }: { candidate: Candidate; params: AnalysisParams; eventTitles: Record<string, string> }) {
  const { reports, active, setActiveId, add, remove } = useReports<InsightsReport>(candidate.id, "insights");
  const [focus, setFocus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      add(await api.insights(candidate.id, { ...params, focus }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <Card
        title="Explain the numbers"
        sub={`Claude reads the polling average, every event's measured impact and what the candidate actually said, then explains what is driving ${metricLabel(params.metric).toLowerCase()} among ${params.segment === "All" ? "all voters" : params.segment}.`}
      >
        <div className="stack-sm">
          <textarea
            className="input"
            rows={2}
            placeholder="Optional: a question to focus on, e.g. “Why are we losing independents since May?”"
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
            style={{ minHeight: 60 }}
          />
          <div className="row" style={{ justifyContent: "space-between" }}>
            <button className="btn primary" onClick={run} disabled={busy}>
              {busy ? "Analyzing…" : "Run analysis"}
            </button>
            <ReportPicker reports={reports} activeId={active?.id ?? null} onPick={setActiveId} onDelete={remove} label={(r) => `${metricLabel(String(r.params.metric))} · ${r.params.segment}`} />
          </div>
          <ErrorNotice error={error} />
        </div>
      </Card>

      {busy && <Working label="Reading the polls and the record. This usually takes 20–60 seconds." />}

      {active && !busy && <InsightsReportView report={active} eventTitles={eventTitles} />}
    </div>
  );
}

function InsightsReportView({ report, eventTitles }: { report: InsightsReport; eventTitles: Record<string, string> }) {
  const o = useMemo(() => replaceIds(report.output, eventTitles), [report, eventTitles]);
  return (
    <div className="stack">
      <Card>
        <div className="stack">
          <div>
            <div className="section-title">
              {metricLabel(String(report.params.metric))} · {String(report.params.segment)}
            </div>
            <div className="report-headline">{o.headline}</div>
          </div>
          <Paragraphs text={o.summary} />
          <div>
            <div className="section-title">Trajectory</div>
            <Paragraphs text={o.trajectory} />
          </div>
          <UsageNote report={report} />
        </div>
      </Card>

      <Card title="What drove the movement">
        <div className="grid cols-2-even">
          {o.key_drivers.map((d, i) => (
            <div className="driver" key={i}>
              <div className="driver-head">
                <strong>{d.title || eventTitles[d.event_id] || d.event_id}</strong>
                <Delta value={d.measured_delta_pp} />
              </div>
              <div className="row">
                <span className={`chip ${d.direction === "positive" ? "good" : d.direction === "negative" ? "bad" : "warn"}`}>
                  {d.direction === "positive" ? "▲ helped" : d.direction === "negative" ? "▼ hurt" : "◆ mixed"}
                </span>
                <span className="chip">{d.confidence} confidence</span>
              </div>
              <p className="small">{d.why_it_landed}</p>
              {d.key_quote && <div className="quote">{d.key_quote}</div>}
            </div>
          ))}
        </div>
      </Card>

      <div className="grid cols-2-even">
        <Card title="Themes">
          <div className="stack-sm">
            {o.themes.map((t, i) => (
              <div key={i} className="small">
                <div className="row" style={{ marginBottom: 2 }}>
                  <strong>{t.theme}</strong>
                  <span className={`chip ${VERDICT_CHIP[t.verdict]}`}>{t.verdict}</span>
                </div>
                <p className="secondary">{t.explanation}</p>
              </div>
            ))}
          </div>
        </Card>
        <Card title="How they talk, and what it does">
          <div className="stack-sm">
            {o.language_patterns.map((p, i) => (
              <div key={i} className="small stack-sm" style={{ gap: 4 }}>
                <div className="row">
                  <strong>{p.pattern}</strong>
                  <span className={`chip ${VERDICT_CHIP[p.effect]}`}>{p.effect}</span>
                </div>
                {p.example_quote && (
                  <div className="quote">
                    {p.example_quote}
                    {eventTitles[p.example_event_id] && <div className="tiny muted">— {eventTitles[p.example_event_id]}</div>}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid cols-2-even">
        <Card title="By segment">
          <div className="stack-sm">
            {o.segments.length === 0 && <p className="muted small">No segment data.</p>}
            {o.segments.map((s, i) => (
              <div key={i} className="small">
                <strong>{s.segment}</strong>
                <p className="secondary">{s.observation}</p>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Risks and caveats">
          <div className="stack">
            <ul className="bullets">
              {o.risks.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
            {o.caveats.length > 0 && (
              <div>
                <div className="section-title">Caveats</div>
                <ul className="bullets secondary small">
                  {o.caveats.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
