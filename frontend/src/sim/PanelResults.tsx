import { Fragment, useMemo, useState } from "react";
import { useReadOnly } from "../readOnly";
import { downloadFile } from "../api";
import { Card, ErrorNotice, Paragraphs } from "../components/ui";
import { AgentModal } from "./AgentModal";
import { Caveats } from "./Caveats";
import { armColor, Histograms, IntervalBars, ShareBars, type IntervalRow } from "./charts";
import { dimLabel, levelLabel, pct, signed } from "./nav";
import type { Arm, PanelResults, Population, Question, SegmentCell, SimMeta, SimRun } from "./types";

const VERDICT_CHIP: Record<string, string> = { strongest: "good", effective: "good", mixed: "warn", ineffective: "", backfires: "bad" };

type Act = (a: "summarize" | "recompute") => Promise<SimRun<PanelResults> | undefined> | unknown;

export function PanelResultsView({ run, pop, meta, act }: { run: SimRun<PanelResults>; pop: Population | null; meta: SimMeta; act: Act }) {
  const readOnly = useReadOnly();
  const res = run.results;
  const arms = (run.config.arms as Arm[]) ?? [];
  const questions = (run.config.questions as Question[]) ?? [];
  const [busy, setBusy] = useState<string | null>(null);
  const [agentId, setAgentId] = useState<string | null>(null);
  if (run.status !== "done" || !res || !res.toplines) return <Caveats kind="panel" population={pop} />;

  const control = arms[0];
  const treatments = arms.slice(1);
  const armIndex = Object.fromEntries(arms.map((a, i) => [a.id, i]));
  const label = (id: string) => arms.find((a) => a.id === id)?.label ?? id;
  const primary = questions.find((q) => q.id === res.primary);
  const vote = questions.find((q) => q.id === "vote_choice");
  const unit = (q?: Question) => (q?.kind === "single_choice" && !q.ordinal ? "pp" : "pts");

  const headlineRows: IntervalRow[] = [];
  if (primary)
    for (const t of treatments) {
      const e = res.effects[t.id]?.[primary.id];
      if (e) headlineRows.push({ key: `p-${t.id}`, label: t.label, sub: primaryLabel(primary), est: e.est, lo: e.lo, hi: e.hi, note: `n = ${e.n} agents, paired with the control` });
    }
  const voteRows: IntervalRow[] = [];
  if (vote)
    for (const t of treatments) {
      const e = res.effects[t.id]?.vote_choice?.options?.[vote.options[0]];
      if (e) voteRows.push({ key: `v-${t.id}`, label: t.label, sub: `vote for ${vote.options[0]}`, est: e.est, lo: e.lo, hi: e.hi });
    }
  const adjRows: IntervalRow[] = treatments.flatMap((t) => {
    const adj = res.backtest_adjusted?.effects?.[t.id];
    return adj ? [{ key: `a-${t.id}`, label: t.label, sub: `β ${res.backtest_adjusted!.beta.toFixed(2)} × simulated`, est: adj.est, lo: adj.lo, hi: adj.hi, note: "Includes uncertainty in β" }] : [];
  });

  async function doAct(a: "summarize" | "recompute") {
    setBusy(a);
    try {
      await act(a);
    } finally {
      setBusy(null);
    }
  }

  const s = res.summary;
  return (
    <div className="stack">
      <Card>
        <div className="stack">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <div className="section-title" style={{ margin: 0 }}>
              {res.n_agents} simulated people · effective n {res.n_eff.toFixed(0)} · {res.weight_set} weights
              {res.n_errors > 0 && ` · ${res.n_errors} failed answers`}
            </div>
            <div className="row">
              {!res.backtest_adjusted && run.candidate_id && <span className="chip warn" title="No backtest for this candidate and population yet">uncalibrated effect sizes</span>}
              {res.backtest_adjusted && <span className="chip accent">backtest-adjusted</span>}
            </div>
          </div>
          {s ? <div className="report-headline">{s.headline}</div> : <div className="report-headline">Results</div>}
          {s && s.arm_comparison.length > 0 && (
            <div className="row">
              {s.arm_comparison.map((a) => (
                <span key={a.arm} className={`chip ${VERDICT_CHIP[a.verdict] ?? ""}`} title={a.why}>
                  {a.arm}: {a.verdict}
                </span>
              ))}
            </div>
          )}
          <div className="grid cols-2-even">
            {headlineRows.length > 0 && (
              <div>
                <div className="section-title">Change in {primary ? primaryLabel(primary) : "the main outcome"} vs control</div>
                <IntervalBars rows={headlineRows} unit={unit(primary)} />
              </div>
            )}
            {voteRows.length > 0 && (
              <div>
                <div className="section-title">Change in vote share for {vote!.options[0]} (pp)</div>
                <IntervalBars rows={voteRows} unit="pp" />
              </div>
            )}
          </div>
          {adjRows.length > 0 && (
            <div>
              <div className="section-title">Expected change in the polls, from the backtest (pts)</div>
              <IntervalBars rows={adjRows} unit="pts" />
            </div>
          )}
          <p className="tiny muted">
            Bars show the average within-person change from the control; whiskers are 95% bootstrap intervals over agents. Colored bars have intervals that exclude zero.
            {adjRows.length > 0 && " The poll estimate rescales the simulated effect by how simulated effects lined up with measured poll movement for this candidate's past events."}
          </p>
        </div>
      </Card>

      {s ? (
        <Card title="Debrief" sub="Written by Claude from the numbers and quotes below.">
          <div className="stack">
            <Paragraphs text={s.summary} />
            {s.themes.length > 0 && (
              <div className="stack-sm">
                <div className="section-title">Themes</div>
                {s.themes.map((t, i) => (
                  <div key={i} className="driver">
                    <div className="driver-head">
                      <strong>{t.theme}</strong>
                      <span className="chip">{t.prevalence}</span>
                    </div>
                    <div className="tiny muted">
                      {t.arms.join(", ")}
                      {t.segments.length > 0 && ` · ${t.segments.join(", ")}`}
                    </div>
                    {t.quotes.map((q, j) => (
                      <div key={j} className="quote">
                        “{q}”
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
            <div className="grid cols-2-even">
              <ListBlock title="Backfire risks" items={s.backfire_risks} />
              <ListBlock title="Recommended edits" items={s.recommended_edits} checklist />
              <ListBlock title="Segment notes" items={s.segment_notes} />
              <ListBlock title="Surprises" items={s.surprises} />
            </div>
            {s.caveats.length > 0 && <ListBlock title="Caveats from the analyst" items={s.caveats} />}
          </div>
        </Card>
      ) : (
        <Card title="Debrief">
          <div className="row">
            <ErrorNotice error={res.summary_error ?? "No debrief yet."} />
            <button className="btn sm" onClick={() => doAct("summarize")} disabled={busy === "summarize"} hidden={readOnly}>
              {busy === "summarize" ? "Writing…" : "Write debrief"}
            </button>
          </div>
        </Card>
      )}

      <Caveats kind="panel" population={pop} />

      <EffectsTable res={res} questions={questions} treatments={treatments} />

      <SegmentsCard res={res} treatments={treatments} primary={primary} vote={vote} />

      <Card title="Answers by arm">
        <div className="stack">
          {questions
            .filter((q) => q.kind === "scale" && q.scale_max - q.scale_min >= 20)
            .map((q) => (
              <div key={q.id}>
                <div className="section-title">{q.text}</div>
                <Histograms
                  lo={q.scale_min}
                  hi={q.scale_max}
                  panels={arms.map((a, i) => ({ key: a.id, label: a.label, color: armColor(i), bins: res.toplines[a.id]?.[q.id]?.hist ?? [], mean: res.toplines[a.id]?.[q.id]?.mean }))}
                />
              </div>
            ))}
          {questions
            .filter((q) => q.kind === "single_choice")
            .map((q) => (
              <div key={q.id}>
                <div className="section-title">{q.text}</div>
                <ShareBars
                  categories={q.options}
                  series={arms.map((a, i) => ({ key: a.id, label: a.label, color: armColor(i), values: res.toplines[a.id]?.[q.id]?.shares ?? {} }))}
                />
              </div>
            ))}
        </div>
      </Card>

      {vote && treatments.length > 0 && <Transitions res={res} vote={vote} treatments={treatments} control={control} />}

      <QuoteWall res={res} arms={arms} armIndex={armIndex} onOpen={setAgentId} label={label} />

      <div className="row">
        <button className="btn sm" onClick={() => downloadFile(`/sim/runs/${run.id}/export.csv`, `${run.title.replace(/[^\w]+/g, "-").toLowerCase()}.csv`)}>
          Export responses (CSV)
        </button>
        <button className="btn ghost sm" onClick={() => doAct("recompute")} disabled={busy === "recompute"} hidden={readOnly} title="Re-aggregate with the population's current weights">
          {busy === "recompute" ? "Recomputing…" : "Recompute with current weights"}
        </button>
        <span className="tiny muted">{meta.model}</span>
      </div>
      {agentId && <AgentModal agentId={agentId} onClose={() => setAgentId(null)} />}
    </div>
  );
}

function primaryLabel(q: Question): string {
  if (q.id === "thermometer") return "feeling thermometer (0–100)";
  if (q.ordinal) return `${q.id.replace(/_/g, " ")} (0–100 score)`;
  if (q.kind === "scale") return `${q.id.replace(/_/g, " ")} (${q.scale_min}–${q.scale_max})`;
  return q.id.replace(/_/g, " ");
}

function ListBlock({ title, items, checklist = false }: { title: string; items: string[]; checklist?: boolean }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="section-title">{title}</div>
      <ul className={checklist ? "checklist" : "bullets"}>
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  );
}

function EffectsTable({ res, questions, treatments }: { res: PanelResults; questions: Question[]; treatments: Arm[] }) {
  const numeric = questions.filter((q) => q.kind === "scale" || q.ordinal);
  if (!numeric.length || !treatments.length) return null;
  return (
    <Card title="All effects" sub="Average within-person change from the control, with 95% intervals.">
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Question</th>
              <th className="num">Control mean</th>
              {treatments.map((t) => (
                <th key={t.id} className="num">
                  {t.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {numeric.map((q) => (
              <tr key={q.id}>
                <td>
                  {q.text}
                  <div className="tiny muted">{q.kind === "scale" ? `${q.scale_min}–${q.scale_max} scale` : "0–100 score from the options"}</div>
                </td>
                <td className="num">{res.toplines.control?.[q.id]?.mean?.toFixed(1) ?? "—"}</td>
                {treatments.map((t) => {
                  const e = res.effects[t.id]?.[q.id];
                  const clear = e && e.lo != null && e.hi != null && (e.lo > 0 || e.hi < 0);
                  return (
                    <td key={t.id} className={`heat ${clear ? ((e!.est ?? 0) > 0 ? "pos" : "neg") : ""}`}>
                      <strong>{signed(e?.est)}</strong>
                      <div className="tiny muted">
                        [{signed(e?.lo)}, {signed(e?.hi)}]
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function SegmentsCard({ res, treatments, primary, vote }: { res: PanelResults; treatments: Arm[]; primary?: Question; vote?: Question }) {
  const [outcome, setOutcome] = useState<"primary" | "vote">(primary ? "primary" : "vote");
  const [treat, setTreat] = useState(treatments[0]?.id ?? "");
  const cells = outcome === "primary" ? res.segments : res.vote_segments;
  const rows = useMemo(() => {
    const by: Record<string, SegmentCell[]> = {};
    for (const c of cells.filter((c) => c.treatment === treat)) (by[c.dim] ??= []).push(c);
    return Object.entries(by).sort(([a], [b]) => (a.startsWith("poll") ? -1 : b.startsWith("poll") ? 1 : 0));
  }, [cells, treat]);
  if (!treatments.length || (!res.segments.length && !res.vote_segments.length)) return null;
  return (
    <Card
      title="By segment"
      sub="Within-person effect for each group. Gray = small group (n < 20); ◆ = survives a false-discovery-rate correction across all these cells."
      actions={
        <>
          {primary && vote && (
            <div className="seg-toggle">
              <button aria-pressed={outcome === "primary"} onClick={() => setOutcome("primary")}>
                {primary.id.replace(/_/g, " ")}
              </button>
              <button aria-pressed={outcome === "vote"} onClick={() => setOutcome("vote")}>
                vote share
              </button>
            </div>
          )}
          {treatments.length > 1 && (
            <select className="input" style={{ width: "auto" }} value={treat} onChange={(e) => setTreat(e.target.value)}>
              {treatments.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
          )}
        </>
      }
    >
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Group</th>
              <th className="num">n</th>
              <th className="num">Control {outcome === "vote" ? "share" : "mean"}</th>
              <th className="num">Effect</th>
              <th className="num">95% interval</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([dim, cs]) => (
              <Fragment key={dim}>
                <tr className="dim-break">
                  <td colSpan={5} className="tiny muted" style={{ fontWeight: 650, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    {dimLabel(dim)}
                  </td>
                </tr>
                {cs.map((c) => {
                  const clear = c.lo != null && c.hi != null && (c.lo > 0 || c.hi < 0);
                  return (
                    <tr key={`${dim}-${c.level}`}>
                      <td>{levelLabel(c.level, { hs_or_less: "HS or less", some_college: "Some college", bachelors: "Bachelor's", postgrad: "Postgrad", dem: "Dem", rep: "Rep", nonvoter: "Didn't vote" })}</td>
                      <td className="num">{c.n}</td>
                      <td className="num">{c.control_mean?.toFixed(1) ?? "—"}</td>
                      <td className={`heat ${c.small ? "small-n" : clear ? ((c.est ?? 0) > 0 ? "pos" : "neg") : ""}`}>
                        {c.fdr && !c.small ? "◆ " : ""}
                        <strong>{signed(c.est)}</strong>
                      </td>
                      <td className="num tiny muted">
                        {signed(c.lo)} to {signed(c.hi)}
                      </td>
                    </tr>
                  );
                })}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {res.unmapped_poll_segments.length > 0 && <p className="tiny muted">Poll segments that couldn't be matched to agent attributes: {res.unmapped_poll_segments.join(", ")}.</p>}
    </Card>
  );
}

function Transitions({ res, vote, treatments, control }: { res: PanelResults; vote: Question; treatments: Arm[]; control: Arm }) {
  const [treat, setTreat] = useState(treatments[0].id);
  const m = res.transitions[treat];
  if (!m) return null;
  const share = (m as unknown as { _row_share: Record<string, number | null> })._row_share ?? {};
  return (
    <Card
      title="Where votes moved"
      sub={`Each row: people who chose that answer under the ${control.label.toLowerCase()}; columns: what they chose after the message.`}
      actions={
        treatments.length > 1 ? (
          <select className="input" style={{ width: "auto" }} value={treat} onChange={(e) => setTreat(e.target.value)}>
            {treatments.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        ) : undefined
      }
    >
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Control answer</th>
              <th className="num">Share</th>
              {vote.options.map((o) => (
                <th key={o} className="num">
                  → {o}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {vote.options
              .filter((o) => (share[o] ?? 0) > 0)
              .map((o) => (
                <tr key={o}>
                  <td>{o}</td>
                  <td className="num">{pct(share[o])}</td>
                  {vote.options.map((p) => (
                    <td key={p} className="num" style={{ fontWeight: o === p ? 400 : (m[o]?.[p] ?? 0) > 0.05 ? 650 : 400, color: o === p ? "var(--muted)" : undefined }}>
                      {pct(m[o]?.[p])}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function QuoteWall({ res, arms, armIndex, onOpen, label }: { res: PanelResults; arms: Arm[]; armIndex: Record<string, number>; onOpen: (id: string) => void; label: (id: string) => string }) {
  const [arm, setArm] = useState<string>("all");
  const quotes = res.quotes.filter((q) => arm === "all" || q.arm_id === arm);
  if (!res.quotes.length) return null;
  return (
    <Card
      title="In their words"
      sub="Open-ended answers, favoring the people whose views moved most. Click one to see who they are."
      actions={
        <select className="input" style={{ width: "auto" }} value={arm} onChange={(e) => setArm(e.target.value)}>
          <option value="all">All arms</option>
          {arms.map((a) => (
            <option key={a.id} value={a.id}>
              {a.label}
            </option>
          ))}
        </select>
      }
    >
      <div className="quote-grid">
        {quotes.slice(0, 36).map((q, i) => (
          <button key={i} className="quote-card" style={{ textAlign: "left", background: "var(--surface)", cursor: "pointer", font: "inherit", color: "inherit" }} onClick={() => onOpen(q.agent_id)}>
            <div className="row who" style={{ justifyContent: "space-between" }}>
              <span className="row">
                <span className="swatch" style={{ background: armColor(armIndex[q.arm_id] ?? 0) }} />
                {label(q.arm_id)}
              </span>
              {q.delta != null && <span>{signed(q.delta)} on headline</span>}
            </div>
            {Object.values(q.texts).map((t, j) => (
              <div key={j}>“{t}”</div>
            ))}
            <div className="who">
              {q.name} · {q.who}
            </div>
          </button>
        ))}
      </div>
    </Card>
  );
}
