import { useEffect, useState } from "react";
import { sim, type SocialInput } from "../api";
import { Card, ErrorNotice, Field, Working } from "../components/ui";
import type { Candidate } from "../types";
import { Caveats } from "./Caveats";
import { goSim, simHref } from "./nav";
import { EstimateLine } from "./RunProgress";
import type { Estimate, Intervention, InterventionTemplate, Population, SimMeta } from "./types";

export const AUTHORS: [string, string][] = [
  ["media_center", "Daily Ledger News (center)"],
  ["media_left", "The Progressive Wire (left)"],
  ["media_right", "Liberty Post (right)"],
  ["official", "Official account (the subject / campaign)"],
];

export function fromTemplate(t: InterventionTemplate, startMinute: number): Intervention[] {
  return t.interventions.map(({ offset_min, ...iv }) => ({ ...JSON.parse(JSON.stringify(iv)), at_minute: startMinute + offset_min, label: t.label }));
}

export function InterventionEditor({ items, onChange, meta, minMinute = 0 }: { items: Intervention[]; onChange: (i: Intervention[]) => void; meta: SimMeta; minMinute?: number }) {
  const update = (i: number, patch: Partial<Intervention>) => onChange(items.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  return (
    <div className="stack-sm">
      {items.map((iv, i) => (
        <div key={i} className="arm-card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong className="small">{iv.label || iv.kind}</strong>
            <div className="row">
              <label className="row tiny muted">
                at
                <input className="input" style={{ width: 70, padding: "2px 6px" }} type="number" min={minMinute} step={10} value={iv.at_minute} onChange={(e) => update(i, { at_minute: Math.max(minMinute, Number(e.target.value) || 0) })} />
                min
              </label>
              <button type="button" className="btn ghost sm danger" onClick={() => onChange(items.filter((_, j) => j !== i))}>
                Remove
              </button>
            </div>
          </div>
          {iv.kind === "event" && iv.event && (
            <>
              <select className="input" value={iv.event.author} onChange={(e) => update(i, { event: { ...iv.event!, author: e.target.value } })}>
                {AUTHORS.map(([k, l]) => (
                  <option key={k} value={k}>
                    Posted by {l}
                  </option>
                ))}
              </select>
              <textarea className="input" rows={3} value={iv.event.text} onChange={(e) => update(i, { event: { ...iv.event!, text: e.target.value } })} />
            </>
          )}
          {iv.kind === "node_control" && iv.node_control && (
            <>
              <div className="tiny muted">
                {iv.node_control.action === "prime" ? "Primes" : iv.node_control.action} {Math.round((iv.node_control.selector.fraction ?? 1) * 100)}% of users for{" "}
                {Math.round((iv.node_control.duration_min ?? 720) / 60)} h:
              </div>
              <textarea className="input" rows={2} value={iv.node_control.text ?? ""} onChange={(e) => update(i, { node_control: { ...iv.node_control!, text: e.target.value } })} />
            </>
          )}
          {iv.kind === "platform_policy" && iv.platform_policy && (
            <div className="tiny muted">
              Ranking weights:{" "}
              {Object.entries(iv.platform_policy)
                .map(([k, v]) => `${k} → ${v}`)
                .join(", ")}
            </div>
          )}
        </div>
      ))}
      <select
        className="input"
        value=""
        onChange={(e) => {
          const t = meta.intervention_templates.find((x) => x.id === e.target.value);
          if (t) onChange([...items, ...fromTemplate(t, minMinute)]);
        }}
      >
        <option value="">+ Add an intervention…</option>
        {meta.intervention_templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.label}: {t.description}
          </option>
        ))}
      </select>
    </div>
  );
}

export function SocialBuilder({ meta, candidates, query }: { meta: SimMeta; candidates: Candidate[]; query: URLSearchParams }) {
  const [pops, setPops] = useState<Population[] | null>(null);
  const candId0 = query.get("cand") ?? "";
  const cand0 = candidates.find((c) => c.id === candId0);
  const [form, setForm] = useState<SocialInput>({
    population_id: query.get("pop") ?? "",
    candidate_id: cand0?.id ?? null,
    title: "",
    focal_subject: cand0?.name.replace(" (demo)", "") ?? "",
    context: "",
    seed_event: { at_minute: 0, kind: "event", label: "The story breaks", event: { author: "media_center", text: "", importance: 1.5, topics: [] } },
    n_agents: 60,
    duration_hours: 12,
    tick_minutes: 10,
    start_clock: "08:00",
    max_calls_per_tick: 12,
    interventions: [],
  });
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof SocialInput>(k: K, v: SocialInput[K]) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    sim
      .populations()
      .then((ps) => {
        const ready = ps.filter((p) => p.ready_count >= 10);
        setPops(ready);
        if (!form.population_id && ready.length) set("population_id", (ready.find((p) => p.candidate_id === candId0) ?? ready[0]).id);
      })
      .catch((e) => setError((e as Error).message));
    if (cand0) sim.candidateContext(cand0.id).then((c) => set("context", c.context)).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const t = setTimeout(() => {
      sim.estimate("social", { n_agents: form.n_agents, duration_hours: form.duration_hours, tick_minutes: form.tick_minutes, max_calls_per_tick: form.max_calls_per_tick }).then(setEstimate).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [form.n_agents, form.duration_hours, form.tick_minutes, form.max_calls_per_tick]);

  const pop = pops?.find((p) => p.id === form.population_id);
  const maxAgents = Math.min(meta.limits.max_social_agents, pop?.ready_count ?? 200);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await sim.createSocial({ ...form, n_agents: Math.min(form.n_agents, maxAgents), title: form.title.trim() || `${form.focal_subject}: ${form.seed_event.event?.text.slice(0, 60)}` });
      goSim(`run/${r.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  if (!pops) return <Working label="Loading…" />;
  if (!pops.length)
    return (
      <Card>
        <div className="empty">
          <h2>No population ready</h2>
          <p className="small">Social scenarios need at least 10 ready agents.</p>
          <a className="btn primary" href={simHref("pop/new")}>
            New population
          </a>
        </div>
      </Card>
    );

  return (
    <div className="stack">
      <div className="sim-head">
        <div>
          <div className="crumbs">
            <a href={simHref()}>Simulations</a> / New social scenario
          </div>
          <h1>Social spread scenario</h1>
          <div className="cand-sub small">A news event hits a simulated feed. Watch how reactions spread hour by hour, then branch to test responses.</div>
        </div>
      </div>
      <form className="grid form-split" onSubmit={run}>
        <div className="stack">
          <Card title="The event">
            <div className="stack-sm">
              <div className="form-grid">
                <Field label="Population">
                  <select className="input" value={form.population_id} onChange={(e) => set("population_id", e.target.value)}>
                    {pops.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} ({p.ready_count})
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Candidate" hint="optional">
                  <select className="input" value={form.candidate_id ?? ""} onChange={(e) => set("candidate_id", e.target.value || null)}>
                    <option value="">None</option>
                    {candidates.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Focal subject" hint="stances are measured toward this">
                  <input className="input" required value={form.focal_subject} onChange={(e) => set("focal_subject", e.target.value)} placeholder="e.g. Acme Foods, Mayor Diaz" />
                </Field>
                <Field label="Run name">
                  <input className="input" value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="optional" />
                </Field>
              </div>
              <Field label="What breaks" hint="the first post everyone can see">
                <select className="input" value={form.seed_event.event?.author} onChange={(e) => set("seed_event", { ...form.seed_event, event: { ...form.seed_event.event!, author: e.target.value } })}>
                  {AUTHORS.map(([k, l]) => (
                    <option key={k} value={k}>
                      Posted by {l}
                    </option>
                  ))}
                </select>
              </Field>
              <textarea
                className="input"
                rows={4}
                required
                value={form.seed_event.event?.text}
                onChange={(e) => set("seed_event", { ...form.seed_event, event: { ...form.seed_event.event!, text: e.target.value } })}
                placeholder="e.g. BREAKING: Acme Foods recalls 2 million jars of peanut butter after salmonella cases in three states. The company knew about the contamination for a week."
              />
              <Field label="Background" hint="optional">
                <textarea className="input" rows={3} value={form.context} onChange={(e) => set("context", e.target.value)} />
              </Field>
            </div>
          </Card>
          <Card title="Planned interventions" sub="Scheduled responses. You can also branch later from any hour to compare responses side by side.">
            <InterventionEditor items={form.interventions} onChange={(iv) => set("interventions", iv)} meta={meta} />
          </Card>
        </div>
        <div className="stack" style={{ position: "sticky", top: 72 }}>
          <Card title="Scale">
            <div className="stack-sm">
              <div className="form-grid">
                <Field label="Agents on the network" hint={`max ${maxAgents}`}>
                  <input className="input" type="number" min={10} max={maxAgents} value={form.n_agents} onChange={(e) => set("n_agents", Number(e.target.value) || 10)} />
                </Field>
                <Field label="Simulated hours">
                  <input className="input" type="number" min={1} max={72} value={form.duration_hours} onChange={(e) => set("duration_hours", Number(e.target.value) || 1)} />
                </Field>
                <Field label="Starts at">
                  <input className="input" type="time" value={form.start_clock} onChange={(e) => set("start_clock", e.target.value)} />
                </Field>
                <Field label="Max activations / 10 min" hint="cost cap">
                  <input className="input" type="number" min={1} max={60} value={form.max_calls_per_tick} onChange={(e) => set("max_calls_per_tick", Number(e.target.value) || 1)} />
                </Field>
              </div>
              {estimate && <EstimateLine est={estimate} />}
              <p className="tiny muted">The estimate is rough: activity follows a self-exciting process, so a heated event costs more calls than a quiet one.</p>
              <ErrorNotice error={error} />
              <button className="btn primary" type="submit" disabled={busy || !form.focal_subject.trim() || !form.seed_event.event?.text.trim()}>
                {busy ? "Starting…" : "Run scenario"}
              </button>
              <Caveats kind="social" population={pop} />
            </div>
          </Card>
        </div>
      </form>
    </div>
  );
}
