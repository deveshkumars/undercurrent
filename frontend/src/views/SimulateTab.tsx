import { useCallback, useEffect, useState } from "react";
import { sim } from "../api";
import { Card, ErrorNotice, Working } from "../components/ui";
import { fmtDate, fmtPts, relTime } from "../format";
import { ProvenanceBadge } from "../sim/Caveats";
import { goSim, KIND_LABEL, simHref } from "../sim/nav";
import { StatusChip } from "../sim/RunProgress";
import type { CandidateSimHub, SegmentMapping } from "../sim/types";
import type { Candidate } from "../types";

export function SimulateTab({ candidate }: { candidate: Candidate }) {
  const [hub, setHub] = useState<CandidateSimHub | null>(null);
  const [popId, setPopId] = useState("");
  const [mapping, setMapping] = useState<SegmentMapping | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [sampleSize, setSampleSize] = useState(60);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    sim
      .candidateHub(candidate.id)
      .then((h) => {
        setHub(h);
        const ready = h.populations.filter((p) => p.ready_count > 0);
        setPopId((cur) => cur || (ready.find((p) => p.candidate_id === candidate.id) ?? ready[0])?.id || "");
        setPicked(new Set(h.eligible_events.filter((e) => e.signal === "clear" || e.signal === "strong").map((e) => e.id).slice(0, 8)));
      })
      .catch((e) => setError((e as Error).message));
  }, [candidate.id]);
  useEffect(load, [load]);
  useEffect(() => {
    if (popId) sim.candidateSegments(candidate.id, popId).then(setMapping).catch(() => setMapping(null));
  }, [candidate.id, popId]);

  if (error) return <ErrorNotice error={error} />;
  if (!hub) return <Working label="Loading simulations…" />;
  const pops = hub.populations.filter((p) => p.ready_count > 0);
  const pop = pops.find((p) => p.id === popId);

  async function start(kind: "calibration" | "backtest") {
    if (!pop) return;
    setBusy(kind);
    setError(null);
    try {
      const r =
        kind === "calibration"
          ? await sim.calibrate(candidate.id, { population_id: pop.id })
          : await sim.backtest(candidate.id, { population_id: pop.id, event_ids: [...picked], sample_size: Math.min(sampleSize, pop.ready_count) });
      goSim(`run/${r.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <Card>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="stack-sm" style={{ maxWidth: 720 }}>
            <strong>Simulate voters' reactions before you go public</strong>
            <p className="small secondary">
              Show a draft ad, speech or post to a population of AI agents modeled on specific voters, then see who moves and why. Calibrate the agents against this
              race's polls and backtest them on its past events so their effects can be read in real-world terms.
            </p>
          </div>
          <div className="row">
            <a className="btn primary" href={simHref("panel/new", { cand: candidate.id, pop: popId || null })}>
              Test a message
            </a>
            <a className="btn" href={simHref("social/new", { cand: candidate.id, pop: popId || null })}>
              Social scenario
            </a>
          </div>
        </div>
      </Card>

      <Card
        title="Population"
        actions={
          <a className="btn sm" href={simHref("pop/new", { cand: candidate.id })}>
            + Population for this race
          </a>
        }
      >
        {pops.length === 0 ? (
          <p className="small muted">No ready population yet. Create one for {candidate.jurisdiction || "this race"}; card-only populations are instant.</p>
        ) : (
          <div className="stack-sm">
            <select className="input" style={{ maxWidth: 420 }} value={popId} onChange={(e) => setPopId(e.target.value)}>
              {pops.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.ready_count} agents){p.candidate_id === candidate.id ? " · linked" : ""}
                </option>
              ))}
            </select>
            {pop && (
              <div className="row small secondary">
                <ProvenanceBadge population={pop} />
                <a href={simHref(`pop/${pop.id}`)}>Open population</a>
              </div>
            )}
          </div>
        )}
      </Card>

      {pop && (
        <div className="grid cols-2-even">
          <Card title="Calibrate against polls" sub="Ask every agent how they'd vote today (no message) and compare with your polling average in each segment.">
            <div className="stack-sm">
              {pop.calibration?.candidate_id === candidate.id ? (
                <div className="row small">
                  <span className={`chip ${pop.calibration.grade === "good" ? "good" : pop.calibration.grade === "fair" ? "warn" : "bad"}`}>
                    last gap {pop.calibration.mae?.toFixed(1) ?? "—"} pts · {pop.calibration.grade}
                  </span>
                  {pop.calibration.applied && <span className="chip accent">calibrated weights ready</span>}
                  <a href={simHref(`run/${pop.calibration.run_id}`)}>view</a>
                </div>
              ) : (
                <p className="small muted">Not calibrated for this candidate yet.</p>
              )}
              {mapping && (
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Poll segment</th>
                        <th className="num">Agents</th>
                        <th className="num">Share of population</th>
                        <th className="num">Share of poll samples</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mapping.segments.map((s) => (
                        <tr key={s.segment}>
                          <td>{s.segment}</td>
                          <td className="num">{s.agents}</td>
                          <td className="num">{Math.round(s.weighted_share * 100)}%</td>
                          <td className="num">{mapping.suggested_targets[s.segment] != null ? `${Math.round(mapping.suggested_targets[s.segment] * 100)}%` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {mapping.unmapped.length > 0 && <p className="tiny muted">Can't map: {mapping.unmapped.join(", ")}</p>}
                </div>
              )}
              <button className="btn sm primary" style={{ alignSelf: "flex-start" }} disabled={!!busy} onClick={() => start("calibration")}>
                {busy === "calibration" ? "Starting…" : `Run calibration (${pop.ready_count} calls)`}
              </button>
            </div>
          </Card>

          <Card title="Backtest on past events" sub="Replay events with measured poll movement, using only the news up to the day before, and compare.">
            <div className="stack-sm">
              {pop.backtest?.candidate_id === candidate.id && (
                <div className="row small">
                  <span className="chip accent">
                    β {pop.backtest.beta?.toFixed(2) ?? "—"} · r {pop.backtest.r?.toFixed(2) ?? "—"}
                  </span>
                  <a href={simHref(`run/${pop.backtest.run_id}`)}>view</a>
                </div>
              )}
              {hub.eligible_events.length === 0 ? (
                <p className="small muted">No events have enough polls before and after them.</p>
              ) : (
                <div style={{ maxHeight: 220, overflow: "auto" }}>
                  {hub.eligible_events.map((e) => (
                    <label key={e.id} className="row small" style={{ padding: "3px 0" }}>
                      <input
                        type="checkbox"
                        checked={picked.has(e.id)}
                        onChange={(ev) => {
                          const next = new Set(picked);
                          if (ev.target.checked) next.add(e.id);
                          else next.delete(e.id);
                          setPicked(next);
                        }}
                      />
                      <span style={{ flex: 1 }}>
                        {fmtDate(e.date)} · {e.title}
                      </span>
                      <span className="tiny muted">
                        {fmtPts(e.delta)} · {e.signal}
                      </span>
                    </label>
                  ))}
                </div>
              )}
              <div className="row small">
                <label className="row">
                  Agents
                  <input className="input" type="number" style={{ width: 80 }} min={5} max={pop.ready_count} value={sampleSize} onChange={(e) => setSampleSize(Number(e.target.value) || 5)} />
                </label>
                <span className="muted">≈ {(Math.min(sampleSize, pop.ready_count) * picked.size * 2).toLocaleString()} calls</span>
              </div>
              <button className="btn sm primary" style={{ alignSelf: "flex-start" }} disabled={!!busy || picked.size < 2} onClick={() => start("backtest")}>
                {busy === "backtest" ? "Starting…" : `Backtest ${picked.size} events`}
              </button>
            </div>
          </Card>
        </div>
      )}

      <Card title="Simulation runs for this candidate">
        {hub.runs.length === 0 && <p className="small muted">None yet.</p>}
        {hub.runs.map((r) => (
          <a key={r.id} className="list-row" href={simHref(`run/${r.id}`)}>
            <div>
              <div className="list-title">{r.title}</div>
              <div className="tiny muted">
                {KIND_LABEL[r.kind]} · {relTime(r.created_at)}
              </div>
            </div>
            <StatusChip status={r.status} />
          </a>
        ))}
      </Card>
    </div>
  );
}
