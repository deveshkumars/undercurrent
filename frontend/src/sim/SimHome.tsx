import { useEffect, useState } from "react";
import { sim } from "../api";
import { Card, ErrorNotice, Working } from "../components/ui";
import { relTime } from "../format";
import { ProvenanceBadge } from "./Caveats";
import { KIND_LABEL, simHref } from "./nav";
import { StatusChip, fmtUsd } from "./RunProgress";
import type { Population, SimRun } from "./types";

export function SimHome() {
  const [pops, setPops] = useState<Population[] | null>(null);
  const [runs, setRuns] = useState<SimRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([sim.populations(), sim.runs()])
      .then(([p, r]) => {
        setPops(p);
        setRuns(r.filter((x) => x.kind !== "populate"));
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  const ready = pops?.filter((p) => p.status === "ready") ?? [];
  return (
    <div className="stack">
      <div className="sim-head">
        <div>
          <h1>Simulations</h1>
          <div className="cand-sub small">Populations of AI agents that react to messages, products and policies the way specific people would.</div>
        </div>
      </div>
      <ErrorNotice error={error} />
      {pops && pops.length === 0 && <HowItWorks />}
      <div className="grid cols-2-even">
        <Card
          title="Populations"
          sub="The people you simulate. Build a stratified sample or import real respondents."
          actions={
            <>
              <a className="btn sm primary" href={simHref("pop/new")}>
                + New population
              </a>
              <a className="btn sm" href={simHref("pop/import")}>
                Import CSV
              </a>
            </>
          }
        >
          {!pops && !error && <Working label="Loading…" />}
          {pops?.length === 0 && <p className="muted small">No populations yet. Start with 50–100 agents to see how it works.</p>}
          <div>
            {pops?.map((p) => (
              <a key={p.id} className="list-row" href={simHref(`pop/${p.id}`)}>
                <div style={{ minWidth: 0 }}>
                  <div className="list-title">{p.name}</div>
                  <div className="row tiny muted" style={{ marginTop: 2 }}>
                    <ProvenanceBadge population={p} />
                    <span>
                      {p.ready_count}/{p.agent_count} ready
                    </span>
                    {p.geography && <span>· {p.geography}</span>}
                    <span>· {relTime(p.created_at)}</span>
                  </div>
                </div>
                <span className={`chip ${p.status === "ready" ? "good" : p.status === "failed" ? "bad" : "accent"}`}>{p.status}</span>
              </a>
            ))}
          </div>
        </Card>
        <Card
          title="Runs"
          sub="Message tests, calibrations, backtests and social scenarios."
          actions={
            <>
              <a className="btn sm primary" href={ready.length ? simHref("panel/new") : undefined} aria-disabled={!ready.length}>
                + Message test
              </a>
              <a className="btn sm" href={ready.length ? simHref("social/new") : undefined} aria-disabled={!ready.length}>
                + Social scenario
              </a>
            </>
          }
        >
          {!runs && !error && <Working label="Loading…" />}
          {runs?.length === 0 && <p className="muted small">{ready.length ? "No runs yet." : "Create a population first; runs need ready agents."}</p>}
          <div>
            {runs?.map((r) => (
              <a key={r.id} className="list-row" href={simHref(`run/${r.id}`)}>
                <div style={{ minWidth: 0 }}>
                  <div className="list-title">{r.title}</div>
                  <div className="tiny muted" style={{ marginTop: 2 }}>
                    {KIND_LABEL[r.kind]} · {r.progress.calls} calls{r.estimate?.billing?.startsWith("api") ? ` · ${fmtUsd(r.progress.usd)}` : ""} · {relTime(r.created_at)}
                  </div>
                </div>
                <StatusChip status={r.status} />
              </a>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function HowItWorks() {
  return (
    <Card title="How simulations work">
      <div className="grid cols-2-even">
        <div className="stack-sm small">
          <strong>Message tests</strong>
          <p className="secondary">
            Each agent is a model given one person's life-history interview (or real survey answers) plus notes from four expert perspectives: a psychologist, a
            behavioral economist, a political scientist and a demographer. This follows Park et al. (2024), whose agents matched 85% of how consistently real people
            answer the General Social Survey. Every agent sees the control and every message variant, so effects are measured within the same people.
          </p>
        </div>
        <div className="stack-sm small">
          <strong>Social spread</strong>
          <p className="secondary">
            Agents follow each other on a simulated feed. A Hawkes process decides who opens the app when; each agent perceives its feed, updates beliefs and emotions,
            picks a motive and acts. This is the POSIM design (2026). Branch from any hour to test an apology, a fact-check or a ranking change against a no-change
            control.
          </p>
        </div>
      </div>
    </Card>
  );
}
