import { useEffect, useMemo, useState } from "react";
import { sim } from "../api";
import { Card, ErrorNotice, Field, Working } from "../components/ui";
import type { Candidate } from "../types";
import { CompositionBars } from "./charts";
import { goSim, levelLabel, simHref } from "./nav";
import { EstimateLine } from "./RunProgress";
import { TargetsEditor } from "./TargetsEditor";
import type { Estimate, Margins, PopulationInput, SimMeta, Weighting } from "./types";

export function PopulationNew({ meta, candidates, candidateId }: { meta: SimMeta; candidates: Candidate[]; candidateId: string | null }) {
  const cand = candidates.find((c) => c.id === candidateId) ?? null;
  const [form, setForm] = useState<PopulationInput>({
    name: cand ? `${cand.jurisdiction || cand.name} likely voters` : "",
    description: "",
    size: 100,
    preset: cand ? "us_likely_voters" : "us_registered_voters",
    targets: {},
    oversample: {},
    persona_mode: "interview",
    card_detail: "light",
    transcript_words: 900,
    reflections_per_expert: 6,
    geography: cand?.jurisdiction ?? "",
    candidate_id: cand?.id ?? null,
  });
  const [preview, setPreview] = useState<{ weighting: Weighting; estimate: Estimate } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof PopulationInput>(k: K, v: PopulationInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const previewKey = useMemo(() => JSON.stringify({ ...form, name: "x", description: "" }), [form]);

  useEffect(() => {
    const t = setTimeout(() => {
      sim
        .previewPopulation({ ...form, name: form.name || "preview" })
        .then((p) => setPreview(p))
        .catch((e) => setError((e as Error).message));
    }, 350);
    return () => clearTimeout(t);
  }, [previewKey]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const pop = await sim.createPopulation(form);
      goSim(`pop/${pop.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const margins = preview?.weighting.margins ?? {};
  return (
    <div className="stack">
      <div className="sim-head">
        <div>
          <div className="crumbs">
            <a href={simHref()}>Simulations</a> / New population
          </div>
          <h1>New population</h1>
        </div>
      </div>
      <form className="grid form-split" onSubmit={create}>
        <Card title="Who to simulate">
          <div className="stack-sm">
            <Field label="Name">
              <input className="input" required value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Pennsylvania likely voters" />
            </Field>
            <div className="form-grid">
              <Field label="Starting frame">
                <select className="input" value={form.preset} onChange={(e) => set("preset", e.target.value)}>
                  {Object.entries(meta.presets).map(([k, p]) => (
                    <option key={k} value={k}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Agents" hint={`max ${meta.limits.max_agents}`}>
                <input className="input" type="number" min={10} max={meta.limits.max_agents} value={form.size} onChange={(e) => set("size", Math.max(10, Math.min(meta.limits.max_agents, Number(e.target.value) || 10)))} />
              </Field>
              <Field label="Place" hint="state, district or city">
                <input className="input" value={form.geography} onChange={(e) => set("geography", e.target.value)} placeholder="e.g. Pennsylvania" />
              </Field>
              <Field label="Link to candidate">
                <select className="input" value={form.candidate_id ?? ""} onChange={(e) => set("candidate_id", e.target.value || null)}>
                  <option value="">None</option>
                  {candidates.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Agent depth">
              <div className="seg-toggle">
                <button type="button" aria-pressed={form.persona_mode === "interview"} onClick={() => set("persona_mode", "interview")}>
                  Interview + expert notes
                </button>
                <button type="button" aria-pressed={form.persona_mode === "demographic"} onClick={() => set("persona_mode", "demographic")}>
                  Card only (instant)
                </button>
              </div>
            </Field>
            <p className="tiny muted">
              {form.persona_mode === "interview"
                ? "Claude writes each person a life-history interview from their demographic card, then four expert perspectives annotate it (Park et al. 2024). One model call per agent."
                : "Agents get only their demographic card and traits. No model calls now; this is the paper's weakest baseline, useful for quick tests and comparisons."}
            </p>
            {form.persona_mode === "interview" && (
              <div className="form-grid">
                <Field label="Interview length" hint="words">
                  <input className="input" type="number" min={300} max={3000} step={100} value={form.transcript_words} onChange={(e) => set("transcript_words", Number(e.target.value) || 900)} />
                </Field>
                <Field label="Notes per expert">
                  <input className="input" type="number" min={3} max={20} value={form.reflections_per_expert} onChange={(e) => set("reflections_per_expert", Number(e.target.value) || 6)} />
                </Field>
              </div>
            )}
            <Field label="What agents see about themselves">
              <select className="input" value={form.card_detail} onChange={(e) => set("card_detail", e.target.value as "light" | "full")}>
                <option value="light">Interview only, no party or ideology labels (less stereotyping)</option>
                <option value="full">Interview plus every demographic label</option>
              </select>
            </Field>
            <details>
              <summary className="small" style={{ cursor: "pointer", fontWeight: 600 }}>
                Adjust the mix {Object.keys(form.targets).length > 0 && <span className="chip accent">{Object.keys(form.targets).length} custom</span>}
              </summary>
              <p className="tiny muted" style={{ margin: "6px 0 10px" }}>
                Percentages for this place. Agents are drawn to match, then survey weights correct what's left.
              </p>
              <TargetsEditor meta={meta} preset={form.preset} targets={form.targets} onChange={(t: Margins) => set("targets", t)} />
            </details>
            <ErrorNotice error={error} />
            <div className="row" style={{ justifyContent: "space-between" }}>
              <button className="btn primary" type="submit" disabled={busy || !form.name.trim()}>
                {busy ? "Creating…" : form.persona_mode === "interview" ? "Create & generate personas" : "Create population"}
              </button>
              {preview && <EstimateLine est={preview.estimate} />}
            </div>
          </div>
        </Card>

        <Card title="Composition" sub="Weighted share of the sample (bar) against the target (black tick).">
          {!preview && <Working label="Sampling…" />}
          {preview && (
            <div className="stack">
              <div className="row small secondary">
                <span>Effective sample {preview.weighting.n_eff.toFixed(0)}</span>
                <span className="dot-sep">design effect {preview.weighting.deff.toFixed(2)}</span>
                {!preview.weighting.converged && <span className="chip warn">targets not fully met</span>}
              </div>
              {preview.weighting.warnings.map((w) => (
                <div key={w} className="notice warn small">
                  {w}
                </div>
              ))}
              <div className="grid cols-2-even">
                {["party", "age_band", "race", "education", "gender", "region", "ideology", "vote_2024"]
                  .filter((v) => margins[v])
                  .map((v) => (
                    <CompositionBars
                      key={v}
                      title={meta.labels[v] ?? v}
                      levels={Object.entries(margins[v]).map(([lvl, c]) => ({ label: levelLabel(lvl, meta.level_labels), ...c }))}
                    />
                  ))}
              </div>
            </div>
          )}
        </Card>
      </form>
    </div>
  );
}
