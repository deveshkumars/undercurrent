import { useMemo, useState } from "react";
import { api } from "../api";
import { ForecastRange } from "../components/MiniCharts";
import { ReportPicker, UsageNote } from "../components/ReportPicker";
import { Card, Delta, ErrorNotice, Field, ImpactBadge, Paragraphs, Working } from "../components/ui";
import { fmtDate, fmtPts, humanize, replaceIds } from "../format";
import { EVENT_TYPES, type AnalysisParams, type Candidate, type ForecastReport } from "../types";
import { useReports } from "./useReports";

const EXAMPLE = {
  title: "Prime-time interview on rent and crime",
  type: "interview",
  venue: "Lakeshore Tonight (Channel 6)",
  audience: "Prime-time TV, older suburban viewers",
  content: `Planned talking points:
- "Rent in this state went up 31 percent in five years. My Homes Within Reach plan builds 60,000 homes, and the Budget Institute scored every dollar."
- On crime: "Look, my opponent's ads are garbage and the press keeps repeating them because they're lazy."
- "I'll put 400 more officers on patrol in the cities with the fastest-rising car thefts, paid for by the investor tax-break repeal."
- Closing: "If you're a nurse or a mechanic, you should be able to afford to live in the town you serve."`,
};

const VERDICT: Record<string, { label: string; chip: string }> = {
  likely_gain: { label: "Likely gain", chip: "good" },
  likely_neutral: { label: "Likely neutral", chip: "" },
  likely_loss: { label: "Likely loss", chip: "bad" },
  high_variance: { label: "High variance", chip: "warn" },
};

export function ForecastView({ candidate, params, eventTitles }: { candidate: Candidate; params: AnalysisParams; eventTitles: Record<string, string> }) {
  const { reports, active, setActiveId, add, remove } = useReports<ForecastReport>(candidate.id, "forecast");
  const [form, setForm] = useState({ title: "", type: "speech", planned_date: "", venue: "", audience: "", content: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value });

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      add(await api.forecast(candidate.id, { ...params, ...form, planned_date: form.planned_date || null }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid form-split">
      <Card title="Forecast an appearance" sub="Paste a draft speech, interview prep, debate answers or an ad script.">
        <form className="stack-sm" onSubmit={run}>
          <Field label="Title">
            <input className="input" required value={form.title} onChange={set("title")} placeholder="e.g. Union hall speech on wages" />
          </Field>
          <div className="form-grid">
            <Field label="Format">
              <select className="input" value={form.type} onChange={set("type")}>
                {EVENT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {humanize(t)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Planned date">
              <input className="input" type="date" value={form.planned_date} onChange={set("planned_date")} />
            </Field>
            <Field label="Venue">
              <input className="input" value={form.venue} onChange={set("venue")} placeholder="Outlet or location" />
            </Field>
            <Field label="Audience">
              <input className="input" value={form.audience} onChange={set("audience")} placeholder="Who will see it" />
            </Field>
          </div>
          <Field label="Draft" hint="transcript, talking points or script">
            <textarea className="input" required minLength={20} rows={12} value={form.content} onChange={set("content")} />
          </Field>
          <ErrorNotice error={error} />
          <div className="row" style={{ justifyContent: "space-between" }}>
            <button className="btn primary" type="submit" disabled={busy}>
              {busy ? "Forecasting…" : "Forecast"}
            </button>
            {candidate.is_demo && (
              <button type="button" className="btn ghost sm" onClick={() => setForm({ ...form, ...EXAMPLE })}>
                Fill an example
              </button>
            )}
          </div>
        </form>
      </Card>

      <div className="stack">
        {reports.length > 0 && (
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="section-title" style={{ margin: 0 }}>
              Saved forecasts
            </span>
            <ReportPicker reports={reports} activeId={active?.id ?? null} onPick={setActiveId} onDelete={remove} label={(r) => String(r.params.title)} />
          </div>
        )}
        {busy && <Working label="Matching the draft to past events and forecasting. This usually takes 30–90 seconds." />}
        {!busy && active && <ForecastResult report={active} eventTitles={eventTitles} />}
        {!busy && !active && (
          <Card>
            <div className="empty">
              <h2>How will it land?</h2>
              <p className="small">
                Undercurrent finds past events like this one, computes how polls moved after them, and has Claude adjust that baseline line by line for what the draft
                actually says.
              </p>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

function ForecastResult({ report, eventTitles }: { report: ForecastReport; eventTitles: Record<string, string> }) {
  const o = useMemo(() => replaceIds(report.output, eventTitles), [report, eventTitles]);
  const { prior, features } = report.quant;
  const v = VERDICT[o.verdict] ?? VERDICT.likely_neutral;
  const risks = o.line_assessments.filter((l) => l.assessment === "risk");
  const strengths = o.line_assessments.filter((l) => l.assessment === "strength");
  return (
    <div className="stack">
      <Card>
        <div className="stack">
          <div className="section-title" style={{ marginBottom: 0 }}>
            {String(report.params.title)} · {humanize(String(report.params.type))}
            {report.params.planned_date ? ` · ${fmtDate(String(report.params.planned_date))}` : ""}
          </div>
          <div className="row" style={{ alignItems: "flex-end", gap: 16 }}>
            <div>
              <div className="tile-label">Expected change in the average</div>
              <div className="hero-num">
                <Delta value={o.predicted_effect_pp} unit={false} threshold={0.25} />
              </div>
            </div>
            <div className="stack-sm" style={{ gap: 4 }}>
              <div className="row">
                <span className={`chip ${v.chip}`}>{v.label}</span>
                <span className="chip">{o.confidence} confidence</span>
              </div>
              <div className="small secondary">
                80% range {fmtPts(o.low_pp)} to {fmtPts(o.high_pp)}
              </div>
            </div>
          </div>
          <div className="report-headline" style={{ fontSize: 17 }}>
            {o.headline}
          </div>
          <ForecastRange prior={prior.range_80} low={o.low_pp} high={o.high_pp} point={o.predicted_effect_pp} />
          <Paragraphs text={o.reception_summary} />
          <details>
            <summary className="small secondary" style={{ cursor: "pointer" }}>
              How this forecast was built
            </summary>
            <div className="stack-sm" style={{ marginTop: 8 }}>
              <Paragraphs text={o.reasoning} />
              <div className="small secondary">
                Read as: {features.topics.join(", ")} · tone {features.tone}. Statistical prior from similar events: {fmtPts(prior.prior_mean)} (sd {prior.prior_sd.toFixed(1)}).
              </div>
            </div>
          </details>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <UsageNote report={report} />
            <a className="btn sm" href={`#/sim/panel/new?cand=${report.candidate_id}&forecast=${report.id}`} title="Show this draft to a population of simulated voters">
              Test on a simulated panel →
            </a>
          </div>
        </div>
      </Card>

      {prior.analogs.length > 0 && (
        <Card title="Most similar past events" sub="How the polls moved after them. These anchor the forecast.">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Date</th>
                  <th className="num">Similarity</th>
                  <th className="num">Measured</th>
                </tr>
              </thead>
              <tbody>
                {prior.analogs.map((a) => (
                  <tr key={a.id}>
                    <td>
                      {a.title}
                      <div className="tiny muted">{humanize(a.type)} · {a.topics.join(", ")}</div>
                    </td>
                    <td>{fmtDate(a.date)}</td>
                    <td className="num">{Math.round(a.similarity * 100)}%</td>
                    <td className="num">
                      <ImpactBadge delta={a.delta} signal={a.signal} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {o.segment_reactions.length > 0 && (
        <Card title="Expected reaction by segment">
          <div className="table-wrap">
            <table className="data">
              <tbody>
                {o.segment_reactions.map((s) => (
                  <tr key={s.segment}>
                    <td style={{ width: 130 }}>
                      <strong>{s.segment}</strong>
                    </td>
                    <td className="num" style={{ width: 90 }}>
                      <Delta value={s.effect_pp} />
                    </td>
                    <td className="secondary small">{s.reasoning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title="Line by line">
        <div className="stack-sm">
          {[...risks, ...strengths].map((l, i) => (
            <div key={i} className={`line-card ${l.assessment}`}>
              <div className="row">
                <span className={`chip ${l.assessment === "risk" ? "bad" : "good"}`}>{l.assessment === "risk" ? "⚠ risk" : "✓ strength"}</span>
              </div>
              <div className="quote">{l.quote}</div>
              <p className="small">{l.why}</p>
              {l.suggested_rewrite && (
                <div className="rewrite">
                  <div className="tiny muted">Try instead</div>
                  {l.suggested_rewrite}
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>

      <div className="grid cols-2-even">
        <Card title="Likely headlines">
          <ul className="bullets">
            {o.likely_headlines.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </Card>
        <Card title="How the opponent will use it">
          <ul className="bullets">
            {o.opponent_attack_lines.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Changes that would improve it">
        <ul className="checklist">
          {o.recommended_changes.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
