import { useEffect, useMemo, useState } from "react";
import { api, sim, type PanelInput } from "../api";
import { Card, ErrorNotice, Field, Working } from "../components/ui";
import { humanize } from "../format";
import type { CampaignEvent, Candidate, ForecastReport } from "../types";
import { Caveats } from "./Caveats";
import { armColor } from "./charts";
import { goSim, simHref } from "./nav";
import { EstimateLine } from "./RunProgress";
import type { Estimate, Population, Question, SimMeta } from "./types";

type ArmDraft = PanelInput["arms"][number];

const FORMAT_BY_EVENT: Record<string, string> = { speech: "speech_excerpt", ad: "ad_script", debate: "debate_clip", social_post: "social_post", policy: "policy_summary" };

const EXAMPLE_ARMS: ArmDraft[] = [
  {
    id: "t1",
    label: "Cost of living",
    kind: "treatment",
    format: "ad_script",
    source: "a 30-second TV ad",
    text: "[Kitchen table, morning] NARRATOR: Rent up 31 percent. Groceries up. Your paycheck? Not so much.\nCANDIDATE: I'll audit every fee this state charges families. If it can't justify itself, it goes.\nNARRATOR: A plan for people who work for a living.",
  },
  {
    id: "t2",
    label: "Attack on opponent",
    kind: "treatment",
    format: "ad_script",
    source: "a 30-second TV ad",
    text: "NARRATOR: For eight years, the incumbent took donor money and handed out tax breaks to the biggest corporations in the state. Your bills went up. Theirs went down. It's time for someone who answers to you.",
  },
];

let armSeq = 3;

const plainName = (name?: string | null) => (name ?? "").replace(/\s*\(demo\)\s*$/, "");

export function PanelBuilder({ meta, candidates, query }: { meta: SimMeta; candidates: Candidate[]; query: URLSearchParams }) {
  const [pops, setPops] = useState<Population[] | null>(null);
  const [popId, setPopId] = useState(query.get("pop") ?? "");
  const [candId, setCandId] = useState<string>(query.get("cand") ?? "");
  const cand = candidates.find((c) => c.id === candId) ?? null;
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState(plainName(cand?.name));
  const [opponent, setOpponent] = useState(plainName(cand?.opponent_name));
  const [context, setContext] = useState("");
  const [control, setControl] = useState<"placebo" | "none">("placebo");
  const [arms, setArms] = useState<ArmDraft[]>([{ id: "t1", label: "Message A", kind: "treatment", format: "ad_script", source: "", text: "" }]);
  const [questionnaire, setQuestionnaire] = useState(cand ? "political" : "political");
  const [custom, setCustom] = useState<Question[]>([]);
  const [sampleSize, setSampleSize] = useState<number | null>(null);
  const [replicates, setReplicates] = useState(1);
  const [weightSet, setWeightSet] = useState<"demographic" | "calibrated">("demographic");
  const [likelyVoter, setLikelyVoter] = useState(false);
  const [events, setEvents] = useState<CampaignEvent[]>([]);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceReport, setSourceReport] = useState<string | null>(query.get("forecast"));

  useEffect(() => {
    sim
      .populations()
      .then((ps) => {
        const ready = ps.filter((p) => p.ready_count > 0);
        setPops(ready);
        if (!popId && ready.length) setPopId((ready.find((p) => p.candidate_id === candId) ?? ready[0]).id);
      })
      .catch((e) => setError((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // candidate: prefill subject/opponent/context and load past events
  useEffect(() => {
    if (!cand) {
      setEvents([]);
      return;
    }
    setSubject(plainName(cand.name));
    setOpponent(plainName(cand.opponent_name));
    sim.candidateContext(cand.id).then((c) => setContext(c.context)).catch(() => {});
    api.events(cand.id).then(setEvents).catch(() => {});
  }, [cand?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // hand-off from the Forecast tab or a past event
  useEffect(() => {
    const fid = query.get("forecast");
    const eid = query.get("event");
    if (fid && cand) {
      api.reports<ForecastReport>(cand.id, "forecast").then((rs) => {
        const r = rs.find((x) => x.id === fid);
        if (!r) return;
        setTitle(`Panel: ${String(r.params.title)}`);
        setArms([{ id: "t1", label: String(r.params.title), kind: "treatment", format: FORMAT_BY_EVENT[String(r.params.type)] ?? "speech_excerpt", source: String(r.params.venue || ""), text: String(r.params.content) }]);
        setSourceReport(fid);
      });
    }
    if (eid && events.length) {
      const e = events.find((x) => x.id === eid);
      if (e) addEvent(e);
    }
  }, [cand?.id, events.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const pop = pops?.find((p) => p.id === popId) ?? null;
  const n = Math.min(sampleSize ?? pop?.ready_count ?? 0, pop?.ready_count ?? 0);
  const preset = questionnaire === "custom" ? [] : (meta.questionnaires[questionnaire] ?? []);
  const nQuestions = preset.length + custom.length;
  const stimTokens = useMemo(() => Math.round(arms.reduce((a, x) => a + (x.text?.length ?? 0), 0) / Math.max(1, arms.length) / 4) + 60, [arms]);

  useEffect(() => {
    if (!pop) return;
    const t = setTimeout(() => {
      sim
        .estimate("panel", {
          n,
          arms: arms.length + 1,
          replicates,
          questions: nQuestions,
          persona_tokens: pop.persona_mode === "demographic" ? 400 : Math.round(pop.transcript_words * 1.35 + pop.reflections_per_expert * 128 + 250),
          stimulus_tokens: stimTokens,
        })
        .then(setEstimate)
        .catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [pop, n, arms.length, replicates, nQuestions, stimTokens]);

  function addEvent(e: CampaignEvent) {
    const text = [e.summary, e.content].filter(Boolean).join("\n\n");
    setArms((as) => [
      ...as.filter((a) => a.text?.trim()),
      { id: `t${armSeq++}`, label: e.title.slice(0, 80), kind: "treatment" as const, format: FORMAT_BY_EVENT[e.type] ?? "news_article", source: e.venue || "", text, source_event_id: e.id },
    ].slice(0, 4));
  }

  const updateArm = (i: number, patch: Partial<ArmDraft>) => setArms((as) => as.map((a, j) => (j === i ? { ...a, ...patch } : a)));

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!pop) return;
    setBusy(true);
    setError(null);
    try {
      const body: PanelInput = {
        population_id: pop.id,
        candidate_id: cand?.id ?? null,
        title: title.trim() || `${arms.map((a) => a.label).join(" vs ")}`.slice(0, 150),
        subject,
        opponent,
        context,
        arms: [{ id: "control", label: control === "placebo" ? "Control (neutral news)" : "Control (nothing)", kind: "control", control_mode: control }, ...arms],
        questionnaire,
        questions: custom,
        sample_size: sampleSize,
        replicates,
        weight_set: weightSet,
        likely_voter: likelyVoter,
        source_report_id: sourceReport,
      };
      const r = await sim.createPanel(body);
      goSim(`run/${r.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  if (pops && pops.length === 0)
    return (
      <Card>
        <div className="empty">
          <h2>No ready population</h2>
          <p className="small">Message tests need agents. Create a population first.</p>
          <a className="btn primary" href={simHref("pop/new", { cand: candId || null })}>
            New population
          </a>
        </div>
      </Card>
    );
  if (!pops) return <Working label="Loading…" />;

  return (
    <div className="stack">
      <div className="sim-head">
        <div>
          <div className="crumbs">
            <a href={simHref()}>Simulations</a> / New message test
          </div>
          <h1>Test a message</h1>
          <div className="cand-sub small">Every agent sees the control and each version, then answers the same questions. Differences are measured within the same people.</div>
        </div>
      </div>
      <form className="grid form-split" onSubmit={run}>
        <div className="stack">
          <Card title="1 · Audience">
            <div className="form-grid">
              <Field label="Population" full>
                <select className="input" value={popId} onChange={(e) => setPopId(e.target.value)}>
                  {pops.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.ready_count} ready)
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Agents to use" hint={`of ${pop?.ready_count ?? 0}`}>
                <input className="input" type="number" min={5} max={pop?.ready_count ?? 500} value={sampleSize ?? pop?.ready_count ?? ""} onChange={(e) => setSampleSize(Number(e.target.value) || null)} />
              </Field>
              <Field label="Repeats per agent" hint="averages out model noise">
                <select className="input" value={replicates} onChange={(e) => setReplicates(Number(e.target.value))}>
                  {[1, 2, 3].map((r) => (
                    <option key={r} value={r}>
                      {r}×
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Weights">
                <select className="input" value={weightSet} onChange={(e) => setWeightSet(e.target.value as typeof weightSet)}>
                  <option value="demographic">Demographic</option>
                  <option value="calibrated" disabled={!pop?.calibration?.applied}>
                    Calibrated to polls{pop?.calibration?.applied ? "" : " (calibrate first)"}
                  </option>
                </select>
              </Field>
              <label className="row small" style={{ alignSelf: "end" }}>
                <input type="checkbox" checked={likelyVoter} onChange={(e) => setLikelyVoter(e.target.checked)} />
                Weight by stated turnout
              </label>
            </div>
          </Card>

          <Card title="2 · What it's about">
            <div className="form-grid">
              <Field label="Candidate" hint="optional">
                <select className="input" value={candId} onChange={(e) => setCandId(e.target.value)}>
                  <option value="">None (product, policy, anything)</option>
                  {candidates.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Run name">
                <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Launch ad A vs B" />
              </Field>
              <Field label="Subject" hint="who or what people react to">
                <input className="input" required value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Sam Rivera, the OatBar, Prop 12" />
              </Field>
              <Field label="Opponent / alternative" hint="for vote-choice questions">
                <input className="input" value={opponent} onChange={(e) => setOpponent(e.target.value)} />
              </Field>
              <Field label="Background every agent knows" hint="no poll numbers" full>
                <textarea className="input" rows={5} value={context} onChange={(e) => setContext(e.target.value)} placeholder="Who the candidate is, what the race is about, or what the product does. Agents can't know a fictional or local race unless you tell them." />
              </Field>
            </div>
          </Card>

          <Card
            title="3 · Messages"
            sub="The control shows neutral local news (or nothing); each version is shown to the same agents separately."
            actions={
              <>
                {events.length > 0 && (
                  <select className="input" style={{ width: "auto" }} value="" onChange={(e) => e.target.value && addEvent(events.find((x) => x.id === e.target.value)!)}>
                    <option value="">+ From a past event…</option>
                    {events.map((ev) => (
                      <option key={ev.id} value={ev.id}>
                        {ev.date} · {ev.title}
                      </option>
                    ))}
                  </select>
                )}
                {!arms.some((a) => a.text?.trim()) && (
                  <button type="button" className="btn ghost sm" onClick={() => setArms(EXAMPLE_ARMS.map((a) => ({ ...a })))}>
                    Fill an example
                  </button>
                )}
              </>
            }
          >
            <div className="stack-sm">
              <div className="arm-card">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <span className="row">
                    <span className="swatch" style={{ background: armColor(0) }} />
                    <strong>Control</strong>
                  </span>
                  <div className="seg-toggle">
                    <button type="button" aria-pressed={control === "placebo"} onClick={() => setControl("placebo")}>
                      Neutral news
                    </button>
                    <button type="button" aria-pressed={control === "none"} onClick={() => setControl("none")}>
                      Nothing
                    </button>
                  </div>
                </div>
              </div>
              {arms.map((a, i) => (
                <div key={a.id} className="arm-card">
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <span className="row" style={{ flex: 1 }}>
                      <span className="swatch" style={{ background: armColor(i + 1) }} />
                      <input className="input" style={{ maxWidth: 260 }} value={a.label} onChange={(e) => updateArm(i, { label: e.target.value })} aria-label="Version name" />
                    </span>
                    {arms.length > 1 && (
                      <button type="button" className="btn ghost sm danger" onClick={() => setArms(arms.filter((_, j) => j !== i))}>
                        Remove
                      </button>
                    )}
                  </div>
                  <div className="form-grid">
                    <Field label="Format">
                      <select className="input" value={a.format} onChange={(e) => updateArm(i, { format: e.target.value })}>
                        {Object.keys(meta.formats).map((f) => (
                          <option key={f} value={f}>
                            {humanize(f)}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Where they saw it" hint="optional">
                      <input className="input" value={a.source} onChange={(e) => updateArm(i, { source: e.target.value })} placeholder="e.g. a TV ad, the local paper" />
                    </Field>
                  </div>
                  <textarea className="input" rows={6} required minLength={10} value={a.text} onChange={(e) => updateArm(i, { text: e.target.value })} placeholder="Paste the ad script, speech excerpt, post, article or product pitch exactly as people would see it." />
                </div>
              ))}
              {arms.length < 4 && (
                <button type="button" className="btn sm" onClick={() => setArms([...arms, { id: `t${armSeq++}`, label: `Message ${String.fromCharCode(65 + arms.length)}`, kind: "treatment", format: "ad_script", source: "", text: "" }])}>
                  + Add a version
                </button>
              )}
            </div>
          </Card>

          <Card title="4 · Questions">
            <div className="stack-sm">
              <div className="seg-toggle">
                {(["political", "product", "policy", "custom"] as const).map((k) => (
                  <button type="button" key={k} aria-pressed={questionnaire === k} onClick={() => setQuestionnaire(k)}>
                    {humanize(k)}
                  </button>
                ))}
              </div>
              {preset.length > 0 && (
                <ol className="small secondary" style={{ margin: 0, paddingLeft: 18 }}>
                  {preset.map((q) => (
                    <li key={q.id}>
                      {q.text.replace(/\{subject\}/g, subject || "the subject").replace(/\{opponent\}/g, opponent || "the opponent")}
                      {q.primary && <span className="chip accent" style={{ marginLeft: 6 }}>headline</span>}
                    </li>
                  ))}
                </ol>
              )}
              <CustomQuestions questions={custom} onChange={setCustom} />
            </div>
          </Card>
        </div>

        <div className="stack" style={{ position: "sticky", top: 72 }}>
          <Card title="Run it">
            <div className="stack-sm">
              {pop && (
                <div className="small secondary">
                  {n} agents × {arms.length + 1} arms × {replicates} = {(n * (arms.length + 1) * replicates).toLocaleString()} answers
                </div>
              )}
              {estimate && <EstimateLine est={estimate} />}
              <ErrorNotice error={error} />
              <button className="btn primary" type="submit" disabled={busy || !pop || !subject.trim() || arms.some((a) => (a.text?.trim().length ?? 0) < 10) || nQuestions === 0}>
                {busy ? "Starting…" : "Run simulation"}
              </button>
              <Caveats kind="panel" population={pop} />
            </div>
          </Card>
        </div>
      </form>
    </div>
  );
}

function slug(text: string, taken: Set<string>): string {
  let base = text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 30) || "q";
  if (!/^[a-z]/.test(base)) base = `q_${base}`;
  let id = base;
  let i = 2;
  while (taken.has(id)) id = `${base}_${i++}`;
  return id;
}

function CustomQuestions({ questions, onChange }: { questions: Question[]; onChange: (q: Question[]) => void }) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState<Question["kind"]>("single_choice");
  const [options, setOptions] = useState("");
  const [range, setRange] = useState("0-10");
  function add() {
    const taken = new Set(questions.map((q) => q.id));
    const [lo, hi] = range.split("-").map((x) => Number(x.trim()));
    const q: Question = {
      id: slug(text, taken),
      text: text.trim(),
      kind,
      options: kind === "single_choice" ? options.split("\n").map((o) => o.trim()).filter(Boolean) : [],
      scale_min: Number.isFinite(lo) ? lo : 0,
      scale_max: Number.isFinite(hi) ? hi : 10,
      scale_labels: [],
    };
    onChange([...questions, q]);
    setText("");
    setOptions("");
  }
  const valid = text.trim().length >= 3 && (kind !== "single_choice" || options.split("\n").filter((o) => o.trim()).length >= 2);
  return (
    <div className="stack-sm">
      {questions.map((q, i) => (
        <div key={q.id} className="row small" style={{ justifyContent: "space-between" }}>
          <span>
            <strong>{q.text}</strong> <span className="muted">· {q.kind === "single_choice" ? q.options.join(" / ") : q.kind === "scale" ? `${q.scale_min}–${q.scale_max}` : "open"}</span>
          </span>
          <button type="button" className="btn ghost sm" onClick={() => onChange(questions.filter((_, j) => j !== i))}>
            Remove
          </button>
        </div>
      ))}
      <details>
        <summary className="small" style={{ cursor: "pointer", fontWeight: 600 }}>
          + Add your own question
        </summary>
        <div className="stack-sm" style={{ marginTop: 8 }}>
          <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Which line stuck with you most?" />
          <div className="row">
            <select className="input" style={{ width: "auto" }} value={kind} onChange={(e) => setKind(e.target.value as Question["kind"])}>
              <option value="single_choice">Multiple choice</option>
              <option value="scale">Scale</option>
              <option value="open">Open-ended</option>
            </select>
            {kind === "scale" && <input className="input" style={{ width: 100 }} value={range} onChange={(e) => setRange(e.target.value)} aria-label="Scale range" />}
          </div>
          {kind === "single_choice" && <textarea className="input" rows={4} value={options} onChange={(e) => setOptions(e.target.value)} placeholder="One option per line" />}
          <button type="button" className="btn sm" disabled={!valid} onClick={add}>
            Add question
          </button>
        </div>
      </details>
    </div>
  );
}
