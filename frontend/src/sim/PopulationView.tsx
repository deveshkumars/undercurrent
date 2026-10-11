import { useCallback, useEffect, useState } from "react";
import { useReadOnly } from "../readOnly";
import { sim } from "../api";
import { Card, ErrorNotice, Modal, Working } from "../components/ui";
import { relTime } from "../format";
import type { Candidate } from "../types";
import { AgentModal } from "./AgentModal";
import { Caveats, ProvenanceBadge } from "./Caveats";
import { CompositionBars } from "./charts";
import { goSim, KIND_LABEL, levelLabel, simHref } from "./nav";
import { RunProgress, StatusChip } from "./RunProgress";
import { TargetsEditor } from "./TargetsEditor";
import type { Agent, Margins, Population, SimMeta, SimRun } from "./types";
import { isActive, useRunDriver } from "./useRunDriver";

const PAGE = 50;

export function PopulationView({ meta, pid, candidates }: { meta: SimMeta; pid: string; candidates: Candidate[] }) {
  const readOnly = useReadOnly();
  const [pop, setPop] = useState<Population | null>(null);
  const [agents, setAgents] = useState<{ total: number; agents: Agent[] } | null>(null);
  const [page, setPage] = useState(0);
  const [runs, setRuns] = useState<SimRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [openAgent, setOpenAgent] = useState<string | null>(null);
  const [reweighting, setReweighting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([sim.population(pid), sim.runs({ population_id: pid })]);
      setPop(p);
      setRuns(r.filter((x) => x.kind !== "populate"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [pid]);

  const loadAgents = useCallback(() => {
    sim.agents(pid, page * PAGE, PAGE).then(setAgents).catch((e) => setError((e as Error).message));
  }, [pid, page]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const driver = useRunDriver(pop?.populate_run_id ?? null, {
    onDone: () => {
      load();
      loadAgents();
    },
  });
  // refresh the agent table as personas arrive
  useEffect(() => {
    if (driver.run && isActive(driver.run)) {
      loadAgents();
      sim.population(pid).then(setPop).catch(() => {});
    }
  }, [driver.run?.cursor]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !pop) return <ErrorNotice error={error} />;
  if (!pop) return <Working label="Loading population…" />;

  const cand = candidates.find((c) => c.id === pop.candidate_id);
  const margins = pop.weighting?.margins ?? {};
  const generating = pop.status === "generating" || (driver.run && isActive(driver.run));
  const ready = pop.ready_count > 0;

  async function remove() {
    if (!pop || !confirm(`Delete "${pop.name}", its ${pop.agent_count} agents and every run that used them?`)) return;
    await sim.deletePopulation(pop.id);
    goSim();
  }

  return (
    <div className="stack">
      <div className="sim-head">
        <div>
          <div className="crumbs">
            <a href={simHref()}>Simulations</a> / Population
          </div>
          <h1>{pop.name}</h1>
          <div className="cand-sub small">
            <ProvenanceBadge population={pop} />
            <span className={`chip ${pop.status === "ready" ? "good" : pop.status === "failed" ? "bad" : "accent"}`}>{pop.status}</span>
            <span>
              {pop.ready_count}/{pop.agent_count} agents ready
            </span>
            {pop.geography && <span className="dot-sep">{pop.geography}</span>}
            {cand && <span className="dot-sep">linked to {cand.name}</span>}
            <span className="dot-sep">{relTime(pop.created_at)}</span>
          </div>
        </div>
        <div className="row" hidden={readOnly}>
          <a className="btn primary" href={ready ? simHref("panel/new", { pop: pop.id, cand: pop.candidate_id }) : undefined} aria-disabled={!ready}>
            Test a message
          </a>
          <a className="btn" href={ready ? simHref("social/new", { pop: pop.id, cand: pop.candidate_id }) : undefined} aria-disabled={!ready}>
            Social scenario
          </a>
          <button className="btn ghost sm" onClick={() => setReweighting(true)}>
            Reweight
          </button>
          <button className="btn ghost sm danger" onClick={remove}>
            Delete
          </button>
        </div>
      </div>
      <ErrorNotice error={error} />

      {driver.run && (generating || driver.run.status !== "done") && (
        <Card title={driver.run.kind === "populate" ? (driver.run.config.mode === "reflections" ? "Writing expert reflections" : "Writing personas") : ""}>
          <RunProgress run={driver.run} driving={driver.driving} watching={driver.watching} error={driver.error} act={driver.act} onChanged={(r) => driver.setRun(r as typeof driver.run)} />
          <p className="tiny muted" style={{ marginTop: 6 }}>
            Keep this tab open while it runs; it does the work in steps. You can leave and resume later.
          </p>
        </Card>
      )}

      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Effective sample</div>
          <div className="tile-value">{pop.weighting?.n_eff?.toFixed(0) ?? "—"}</div>
          <div className="tile-foot">of {pop.agent_count} agents after weighting</div>
        </div>
        <div className="tile">
          <div className="tile-label">Design effect</div>
          <div className="tile-value">{pop.weighting?.deff?.toFixed(2) ?? "—"}</div>
          <div className="tile-foot">{(pop.weighting?.deff ?? 1) > 1.5 ? "weights are working hard" : "weights are modest"}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Calibration</div>
          <div className="tile-value">{pop.calibration?.mae != null ? `${pop.calibration.mae.toFixed(1)} pts` : "—"}</div>
          <div className="tile-foot">
            {pop.calibration ? (
              <>
                avg gap to polls · {pop.calibration.grade}
                {pop.calibration.applied && pop.calibration.mae_after != null && ` · ${pop.calibration.mae_after.toFixed(1)} after weighting`}
              </>
            ) : (
              "not calibrated against polls"
            )}
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">Backtest slope</div>
          <div className="tile-value">{pop.backtest?.beta != null ? `β ${pop.backtest.beta.toFixed(2)}` : "—"}</div>
          <div className="tile-foot">{pop.backtest ? `r ${pop.backtest.r?.toFixed(2) ?? "—"} over ${pop.backtest.n_events} events` : "not backtested"}</div>
        </div>
      </div>

      <Caveats kind="population" population={pop} />

      <div className="grid cols-2">
        <Card title="Agents" sub="Click anyone to read their interview, expert notes and answers.">
          {!agents && <Working label="Loading agents…" />}
          {agents && (
            <>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Age</th>
                      <th>Gender</th>
                      <th>Race</th>
                      <th>Education</th>
                      <th>Party</th>
                      <th>Work</th>
                      <th className="num">Weight</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {agents.agents.map((a) => (
                      <tr key={a.id} onClick={() => setOpenAgent(a.id)} style={{ cursor: "pointer" }}>
                        <td>
                          <strong>{a.first_name}</strong>
                        </td>
                        <td>{a.demographics.age ?? a.demographics.age_band ?? "—"}</td>
                        <td>{a.demographics.gender ?? "—"}</td>
                        <td>{a.demographics.race ?? "—"}</td>
                        <td>{a.demographics.education ? levelLabel(a.demographics.education, meta.level_labels) : "—"}</td>
                        <td>
                          {a.demographics.party ?? "—"}
                          {a.demographics.party === "independent" && a.demographics.lean && a.demographics.lean !== "none" ? ` (${a.demographics.lean})` : ""}
                        </td>
                        <td className="secondary">{a.traits.occupation}</td>
                        <td className="num">{a.weight.toFixed(2)}</td>
                        <td>
                          {a.persona_status === "ready" ? (
                            <span className="tiny muted">✓</span>
                          ) : a.persona_status === "failed" ? (
                            <span className="chip bad">failed</span>
                          ) : (
                            <span className="tiny muted">…</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {agents.total > PAGE && (
                <div className="row" style={{ justifyContent: "space-between", marginTop: 10 }}>
                  <span className="tiny muted">
                    {page * PAGE + 1}–{Math.min(agents.total, (page + 1) * PAGE)} of {agents.total}
                  </span>
                  <div className="row">
                    <button className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
                      Previous
                    </button>
                    <button className="btn sm" disabled={(page + 1) * PAGE >= agents.total} onClick={() => setPage(page + 1)}>
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
        <div className="stack">
          <Card title="Composition" sub="Weighted share (bar) against the target (black tick).">
            <div className="stack">
              {["party", "age_band", "race", "education", "gender", "region"]
                .filter((v) => margins[v])
                .map((v) => (
                  <CompositionBars key={v} title={meta.labels[v] ?? v} levels={Object.entries(margins[v]).map(([lvl, c]) => ({ label: levelLabel(lvl, meta.level_labels), ...c }))} />
                ))}
              {pop.weighting?.warnings?.map((w) => (
                <div key={w} className="notice warn small">
                  {w}
                </div>
              ))}
            </div>
          </Card>
          <Card title="Runs with this population">
            {runs.length === 0 && <p className="muted small">None yet.</p>}
            {runs.map((r) => (
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
      </div>
      {openAgent && <AgentModal agentId={openAgent} onClose={() => setOpenAgent(null)} />}
      {reweighting && (
        <ReweightModal
          meta={meta}
          pop={pop}
          onClose={() => setReweighting(false)}
          onSaved={(p) => {
            setPop(p);
            setReweighting(false);
            loadAgents();
          }}
        />
      )}
    </div>
  );
}

function ReweightModal({ meta, pop, onClose, onSaved }: { meta: SimMeta; pop: Population; onClose: () => void; onSaved: (p: Population) => void }) {
  const [targets, setTargets] = useState<Margins>(pop.targets ?? {});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    setBusy(true);
    try {
      onSaved(await sim.reweight(pop.id, targets));
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <Modal title="Reweight population" onClose={onClose} width={860}>
      <p className="small secondary" style={{ marginBottom: 12 }}>
        Change the target mix without regenerating anyone. Survey weights are re-raked; existing runs keep their results (use Recompute on a run to apply new weights).
      </p>
      <TargetsEditor meta={meta} preset={pop.preset || "us_registered_voters"} targets={targets} onChange={setTargets} />
      <ErrorNotice error={error} />
      <div className="modal-actions">
        <button className="btn" onClick={onClose}>
          Cancel
        </button>
        <button className="btn primary" onClick={save} disabled={busy}>
          {busy ? "Reweighting…" : "Reweight"}
        </button>
      </div>
    </Modal>
  );
}
