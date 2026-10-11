import { useEffect, useState } from "react";
import { sim } from "../api";
import { Card, ErrorNotice, Working } from "../components/ui";
import { relTime } from "../format";
import type { Candidate } from "../types";
import { BacktestResultsView, CalibrationResultsView } from "./CandidateResults";
import { Caveats, ProvenanceBadge } from "./Caveats";
import { goSim, KIND_LABEL, simHref } from "./nav";
import { PanelResultsView } from "./PanelResults";
import { RunProgress } from "./RunProgress";
import { SocialRunView } from "./SocialRunView";
import type { BacktestResults, CalibrationResults, PanelResults, Population, SimMeta, SimRun } from "./types";
import { useRunDriver } from "./useRunDriver";

export function RunView({ meta, rid, candidates }: { meta: SimMeta; rid: string; candidates: Candidate[] }) {
  const driver = useRunDriver<unknown>(rid);
  const { run } = driver;
  const [pop, setPop] = useState<Population | null>(null);
  useEffect(() => {
    if (run?.population_id && pop?.id !== run.population_id) sim.population(run.population_id).then(setPop).catch(() => {});
  }, [run?.population_id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!run) return driver.error ? <ErrorNotice error={driver.error} /> : <Working label="Loading run…" />;
  const cand = candidates.find((c) => c.id === run.candidate_id);

  async function remove() {
    if (!run || !confirm("Delete this run and all its responses?")) return;
    await sim.deleteRun(run.id);
    goSim(pop ? `pop/${pop.id}` : "");
  }

  return (
    <div className="stack">
      <div className="sim-head">
        <div>
          <div className="crumbs">
            <a href={simHref()}>Simulations</a>
            {pop && (
              <>
                {" / "}
                <a href={simHref(`pop/${pop.id}`)}>{pop.name}</a>
              </>
            )}
            {run.parent_run_id && (
              <>
                {" / "}
                <a href={simHref(`run/${run.parent_run_id}`)}>parent run</a>
              </>
            )}
          </div>
          <h1>{run.title}</h1>
          <div className="cand-sub small">
            <span className="chip">{KIND_LABEL[run.kind]}</span>
            {pop && <ProvenanceBadge population={pop} />}
            {cand && <span>{cand.name}</span>}
            <span className="dot-sep">{run.config.n_agents ?? "—"} agents</span>
            <span className="dot-sep">{run.model}</span>
            <span className="dot-sep">{relTime(run.created_at)}</span>
          </div>
        </div>
        <div className="row">
          {run.kind === "panel" && run.status === "done" && (
            <a className="btn sm" href={simHref("panel/new", { pop: run.population_id, cand: run.candidate_id })}>
              New test
            </a>
          )}
          <button className="btn ghost sm danger" onClick={remove}>
            Delete
          </button>
        </div>
      </div>

      {run.status !== "done" && (
        <Card>
          <RunProgress run={run} driving={driver.driving} watching={driver.watching} error={driver.error} act={driver.act} onChanged={(r) => driver.setRun(r as typeof run)} />
        </Card>
      )}
      {run.status === "done" && (driver.error || run.error) && <ErrorNotice error={driver.error || run.error} />}

      {run.kind === "populate" && (
        <Card>
          <p className="small">
            This run generated personas for <a href={simHref(`pop/${run.population_id}`)}>{pop?.name ?? "a population"}</a>.
          </p>
        </Card>
      )}
      {run.kind === "panel" && <PanelResultsView run={run as SimRun<PanelResults>} pop={pop} meta={meta} act={driver.act} />}
      {run.kind === "calibration" && run.status === "done" && (
        <CalibrationResultsView run={run as SimRun<CalibrationResults>} act={driver.act} />
      )}
      {run.kind === "backtest" && run.status === "done" && <BacktestResultsView run={run as SimRun<BacktestResults>} />}
      {run.kind === "social" && <SocialRunView run={run} meta={meta} />}
      {run.kind !== "panel" && run.kind !== "populate" && <Caveats kind={run.kind} population={pop} />}
    </div>
  );
}
