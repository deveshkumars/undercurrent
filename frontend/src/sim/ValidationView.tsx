import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Card, ErrorNotice, Working } from "../components/ui";
import { levelLabel, pct } from "./nav";
import { fmtUsd } from "./RunProgress";
import type { ConditionScores, ExperimentResults, ValidationResults } from "./types";

const CONDITIONS: { id: string; label: string; note: string }[] = [
  { id: "interview", label: "Interview agents", note: "Synthetic life-history interview + expert notes, light card (the app's default agent)" },
  { id: "card", label: "Card-only agents", note: "Full card: demographics plus seeded traits, no interview" },
  { id: "demographics", label: "Demographics-only prompt", note: "Just the evaluated attributes, like OpinionQA's steering prompts" },
  { id: "uniform", label: "Uniform random", note: "Every option equally likely (no model calls)" },
  { id: "overall_distribution", label: "Real U.S. topline for every group", note: "Knows the real overall answer, nothing about groups (no model calls)" },
];

const ATTR_LABEL: Record<string, string> = {
  region: "Region",
  age: "Age",
  gender: "Gender",
  race: "Race / ethnicity",
  education: "Education",
  income: "Income",
  party: "Party ID",
  ideology: "Ideology",
};

const LEVEL_LABEL: Record<string, string> = {
  hs_or_less: "HS or less",
  some_college: "Some college",
  bachelors: "Bachelor's",
  postgrad: "Postgrad",
  "<30k": "Under $30k",
  "30-100k": "$30k–100k",
  "100k+": "$100k+",
};

function r3(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(3);
}

function groupLabel(key: string): string {
  const [attr, level] = key.split("=");
  return `${ATTR_LABEL[attr] ?? attr}: ${levelLabel(level, LEVEL_LABEL)}`;
}

export function ValidationView() {
  const [res, setRes] = useState<ValidationResults | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .validation()
      .then(setRes)
      .catch((e) => (e instanceof ApiError && e.status === 404 ? setMissing(true) : setError((e as Error).message)));
  }, []);

  return (
    <div className="stack">
      <div className="sim-head">
        <div>
          <h1>Validation</h1>
          <div className="cand-sub small">How closely simulated respondents reproduce real Americans' answers to real survey questions.</div>
        </div>
      </div>
      <ErrorNotice error={error} />
      {missing && (
        <div className="notice warn">
          No validation results on this deployment yet. Run <code>scripts/fetch_opinionqa.py</code> and then <code>scripts/validate.py --split test</code>.
        </div>
      )}
      {!res && !missing && !error && <Working label="Loading…" />}
      {res && <Results res={res} />}
    </div>
  );
}

function Results({ res }: { res: ValidationResults }) {
  const sc = res.scores;
  const shown = CONDITIONS.filter((c) => sc[c.id]);
  const modelConds = shown.filter((c) => ["interview", "card", "demographics"].includes(c.id));
  const groups = Object.keys(sc[shown[0].id]?.groups ?? {});
  const totalUsd = Object.values(res.runs).reduce((a, r) => a + r.usd_list_price, 0) + (res.population_run?.usd_list_price ?? 0);
  const totalCalls = Object.values(res.runs).reduce((a, r) => a + r.calls, 0) + (res.population_run?.calls ?? 0);

  return (
    <>
      <Summary res={res} />

      <Card title="What was measured">
        <div className="stack-sm small">
          <p>
            <b>Benchmark:</b> OpinionQA (Santurkar et al., 2023): Pew American Trends Panel questions with weighted answers from real respondents. {res.n_questions} held-out
            questions on technology, science, health, the economy and daily life (waves {res.waves.map((w) => `W${w}`).join(", ")}), from {res.n_eligible_questions} that qualified.
            Agents saw only the question wording and options, never the real answers.
          </p>
          <p>
            <b>Score:</b> representativeness R = 1 − the earth mover's distance between the simulated and real answer distributions, scaled to the width of the answer scale and
            averaged over questions. 1 means identical distributions. Group scores compare each simulated group (e.g. simulated Republicans) with the same real group.
          </p>
          <p>
            <b>Setup:</b> {res.n_agents} agents from one population of {res.population.size} matched to the panel's demographics, raked to its margins (design effect{" "}
            {res.weighting.deff}). Every condition asked the same people. Model <code>{res.model}</code> via {res.backend === "claude-cli" ? "the Claude Code CLI" : "the Anthropic API"},{" "}
            {res.date}. {totalCalls.toLocaleString()} calls, {fmtUsd(totalUsd)} API-equivalent cost{res.backend === "claude-cli" ? " (what the same tokens would cost on the Anthropic API; this run was billed to a Claude Code subscription)" : ""}.
          </p>
        </div>
      </Card>

      <Card title="Overall and by group" sub="Higher is closer to the real answers. The last two rows are references, not simulations.">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Condition</th>
                <th className="num">Overall R</th>
                <th className="num">Mean group R</th>
                <th className="num">Worst group R</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => (
                <ScoreRow key={c.id} label={c.label} note={c.note} s={sc[c.id]} />
              ))}
              <tr>
                <td>
                  <div>Sampling ceiling</div>
                  <div className="tiny muted">Real respondents subsampled to the same group sizes: the best a perfect simulator could score with this many agents</div>
                </td>
                <td className="num">{r3(res.ceiling.overall.R)}</td>
                <td className="num">{r3(res.ceiling.group_mean)}</td>
                <td className="num">{r3(res.ceiling.group_worst)}</td>
              </tr>
              <tr>
                <td>
                  <div>Real groups vs the overall population</div>
                  <div className="tiny muted">OpinionQA's human reference: how much real groups differ from the topline on these questions</div>
                </td>
                <td className="num">—</td>
                <td className="num">{r3(res.human_groups_vs_overall.mean)}</td>
                <td className="num">{r3(res.human_groups_vs_overall.worst)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="tiny muted" style={{ marginTop: 10 }}>
          For scale, the OpinionQA paper reports R of 0.70–0.82 for 2023 language models against the overall U.S. population on its full question set, and 0.949 (mean) / 0.865
          (worst) for real demographic groups against the overall population. Different questions and groups, so compare loosely.
        </p>
      </Card>

      {res.real_dispersion && (
        <Card title="Why: too little disagreement" sub="How spread out the answers are, averaged over questions.">
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th />
                  <th className="num">Spread (entropy, 0–1)</th>
                  <th className="num">Share giving the most common answer</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Real respondents</td>
                  <td className="num">{r3(res.real_dispersion.entropy)}</td>
                  <td className="num">{pct(res.real_dispersion.modal_share)}</td>
                </tr>
                {modelConds.map((c) =>
                  sc[c.id].dispersion ? (
                    <tr key={c.id}>
                      <td>{c.label}</td>
                      <td className="num">{r3(sc[c.id].dispersion!.entropy)}</td>
                      <td className="num">{pct(sc[c.id].dispersion!.modal_share)}</td>
                    </tr>
                  ) : null,
                )}
              </tbody>
            </table>
          </div>
          <p className="small secondary" style={{ marginTop: 10 }}>
            Simulated respondents pile onto one answer and rarely pick the strongest options, so their distributions are narrower than real ones. That, more than
            getting the direction wrong, is what keeps them from beating an even spread. Treat simulated levels and splits as rough and too uniform within groups.
          </p>
        </Card>
      )}

      <Card title="By group" sub="R per group. Bold marks the best simulated condition in each row.">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Group</th>
                <th className="num">Agents</th>
                {modelConds.map((c) => (
                  <th key={c.id} className="num">
                    {c.label}
                  </th>
                ))}
                <th className="num">Real topline</th>
                <th className="num">Ceiling</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const vals = modelConds.map((c) => sc[c.id].groups[g]?.R ?? null);
                const best = Math.max(...vals.map((v) => v ?? -1));
                return (
                  <tr key={g}>
                    <td>{groupLabel(g)}</td>
                    <td className="num">{res.group_sizes[g] ?? 0}</td>
                    {vals.map((v, i) => (
                      <td key={modelConds[i].id} className="num" style={{ fontWeight: v != null && v === best ? 600 : undefined }}>
                        {r3(v)}
                      </td>
                    ))}
                    <td className="num">{r3(sc.overall_distribution?.groups[g]?.R)}</td>
                    <td className="num">{r3(res.ceiling.groups[g]?.R)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Runs" sub="Usage as reported by the model backend. Cost is API-equivalent: the same tokens at Anthropic API list price.">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Run</th>
                <th className="num">Calls</th>
                <th className="num">Input (uncached)</th>
                <th className="num">Cache write</th>
                <th className="num">Cache read</th>
                <th className="num">Output</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {[...(res.population_run ? [["Persona generation", res.population_run] as const] : []), ...Object.entries(res.runs)].map(([k, r]) => (
                <tr key={k}>
                  <td>{CONDITIONS.find((c) => c.id === k)?.label ?? k}</td>
                  <td className="num">{r.calls.toLocaleString()}</td>
                  <td className="num">{r.input_tokens.toLocaleString()}</td>
                  <td className="num">{r.cache_creation_input_tokens.toLocaleString()}</td>
                  <td className="num">{r.cache_read_input_tokens.toLocaleString()}</td>
                  <td className="num">{r.output_tokens.toLocaleString()}</td>
                  <td className="num">{fmtUsd(r.usd_list_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="tiny muted" style={{ marginTop: 10 }}>
          Command: <code>{res.command}</code>
        </p>
      </Card>

      {res.experiments && <Experiments ex={res.experiments} />}

      <details className="caveats">
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>How far to trust this</summary>
        <ul>
          <li>Distributions are compared group by group, not person by person: a good score means simulated groups answer like real groups, not that any agent matches a real person.</li>
          <li>Personas here are synthetic. Agents built from real people's interviews or survey answers (CSV import) can do better; this measures the default synthetic setup.</li>
          <li>The surveys ran in 2017–2019. Agents were told so, but the model's knowledge runs later, which can shift answers on topics that changed.</li>
          <li>Group definitions follow the agent card, so some OpinionQA groups are merged (education, income, ideology) and some aren't evaluated (religion, marital status, citizenship).</li>
          <li>Intervals resample questions; they show how much the score depends on which questions were asked, not model randomness.</li>
        </ul>
      </details>
    </>
  );
}

function Summary({ res }: { res: ValidationResults }) {
  const sc = res.scores;
  const best = ["interview", "card", "demographics"]
    .filter((c) => sc[c])
    .sort((a, b) => (sc[b].overall.R ?? 0) - (sc[a].overall.R ?? 0))[0];
  const label = CONDITIONS.find((c) => c.id === best)?.label ?? best;
  const uni = sc.uniform?.overall.R ?? null;
  const top = sc[best]?.overall.R ?? null;
  const beats = top != null && uni != null && (sc[best].overall.lo ?? top) > uni;
  return (
    <div className={`notice ${beats ? "" : "warn"}`}>
      <b>Headline:</b> the best simulated condition ({label.toLowerCase()}) scored R = {r3(top)} overall, against {r3(uni)} for a uniform-random guess
      {beats ? "." : ", so on these questions it does not beat random."} Using the real overall answer for every group scores {r3(sc.overall_distribution?.group_mean)} on
      groups; the simulations score {r3(sc[best]?.group_mean)}.
    </div>
  );
}

function ScoreRow({ label, note, s }: { label: string; note: string; s: ConditionScores }) {
  const o = s.overall;
  return (
    <tr>
      <td>
        <div>{label}</div>
        <div className="tiny muted">{note}</div>
      </td>
      <td className="num">
        {r3(o.R)}
        {o.lo != null && o.hi != null && (
          <div className="tiny muted">
            {r3(o.lo)}–{r3(o.hi)}
          </div>
        )}
      </td>
      <td className="num">{r3(s.group_mean)}</td>
      <td className="num">{r3(s.group_worst)}</td>
    </tr>
  );
}

function fmtVal(kind: string, v: number | null): string {
  if (v == null) return "—";
  return kind === "share" ? `${v.toFixed(1)}%` : v >= 100 ? Math.round(v).toLocaleString() : v.toFixed(2);
}

function Experiments({ ex }: { ex: ExperimentResults }) {
  return (
    <Card
      title="Classic survey experiments"
      sub={`Each condition shown to the same ${ex.n_agents} agents in separate calls; compared with Many Labs 1 (Klein et al., 2014) and the original studies. Paraphrases use new numbers and settings, in case the model memorized the textbook versions.`}
    >
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Experiment</th>
              <th>Measure</th>
              <th className="num">Simulated</th>
              <th className="num">Difference [95% CI]</th>
              <th className="num">Published</th>
              <th>Direction</th>
            </tr>
          </thead>
          <tbody>
            {ex.experiments.map((e) => {
              const [a, b] = e.contrast;
              const r = e.result;
              const p = e.published;
              return (
                <tr key={e.id}>
                  <td>{e.label}</td>
                  <td className="tiny">{e.measure}</td>
                  <td className="num">
                    {a} {fmtVal(e.kind, r.value_a)}
                    <br />
                    {b} {fmtVal(e.kind, r.value_b)}
                  </td>
                  <td className="num">
                    {fmtVal(e.kind === "share" ? "mean" : e.kind, r.diff)}
                    {e.kind === "share" ? " pts" : ""}
                    <div className="tiny muted">
                      {r.diff_ci95[0] != null ? `${fmtVal("mean", r.diff_ci95[0])} to ${fmtVal("mean", r.diff_ci95[1])}` : ""}
                    </div>
                  </td>
                  <td className="num">
                    {p ? (
                      <>
                        {a} {fmtVal(e.kind, p.values[a])}
                        <br />
                        {b} {fmtVal(e.kind, p.values[b])}
                        <div className="tiny muted">{p.source}</div>
                      </>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    {r.direction_matches == null ? (
                      <span className="muted small">no reference</span>
                    ) : r.direction_matches ? (
                      r.diff_vs_published != null && (r.diff_vs_published < 0.25 || r.diff_vs_published > 4) ? (
                        <span className="chip warn">direction only; size far off</span>
                      ) : (
                        <span className="chip good">matches</span>
                      )
                    ) : (
                      <span className="chip bad">doesn't match</span>
                    )}
                    {r.diff_vs_published != null && <div className="tiny muted">{r.diff_vs_published.toFixed(2)}× published difference</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="tiny muted" style={{ marginTop: 10 }}>
        "Matches" means the simulated difference has the published sign and its 95% interval excludes zero; when it is under a quarter or over four times the published
        difference, it is marked as matching in direction only. Many Labs 1 pooled U.S. and international samples. Command:{" "}
        <code>{ex.command}</code>
      </p>
    </Card>
  );
}
