import { useEffect, useState } from "react";
import { sim } from "../api";
import { Card, ErrorNotice, Working } from "../components/ui";
import { relTime } from "../format";
import { ProvenanceBadge } from "./Caveats";
import { KIND_LABEL, signed, simHref } from "./nav";
import { StatusChip, fmtUsd } from "./RunProgress";
import type { DemoList, DemoRun, Population, SimRun } from "./types";

export function SimHome() {
  const [pops, setPops] = useState<Population[] | null>(null);
  const [runs, setRuns] = useState<SimRun[] | null>(null);
  const [demos, setDemos] = useState<DemoList | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([sim.populations(), sim.runs()])
      .then(([p, r]) => {
        setPops(p);
        setRuns(r.filter((x) => x.kind !== "populate"));
      })
      .catch((e) => setError((e as Error).message));
    sim
      .demos()
      .then(setDemos)
      .catch(() => setDemos(null)); // the demos are optional; the rest of the page works without them
  }, []);

  const ready = pops?.filter((p) => p.status === "ready") ?? [];
  return (
    <div className="stack">
      <div className="hero">
        <h1>Test messages on simulated audiences before you ship them.</h1>
        <p className="secondary">
          Show an ad, a product pitch, a policy or a crisis response to a population of AI agents modeled on different kinds of people. See who moves and why, and
          watch how news spreads on a simulated feed. Use it to compare options and catch risks early, not as a poll: simulated people agree with each other more than
          real ones do (<a href="#/validation">see how they scored against real survey answers</a>).
        </p>
      </div>
      <ErrorNotice error={error} />
      {demos && demos.runs.length > 0 && <Demos demos={demos} />}
      {pops && pops.filter((p) => !p.demo).length === 0 && <HowItWorks />}
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

function Demos({ demos }: { demos: DemoList }) {
  const product = demos.runs.find((r) => r.kind === "panel");
  const socials = demos.runs.filter((r) => r.kind === "social");
  const base = socials.find((r) => !r.parent_run_id);
  const branches = socials.filter((r) => r.parent_run_id);
  return (
    <Card title="Try the demos" sub="Two finished scenarios with fictional brands, saved from real runs, so they open instantly.">
      <div className="grid cols-2-even">
        {product && (
          <a className="demo-card" href={simHref(`run/${product.id}`)}>
            <div className="tiny muted">Message test · product launch</div>
            <div className="list-title">{product.title}</div>
            <p className="small secondary">A control and three ads (savings, comfort, climate) shown to the same simulated U.S. adults.</p>
            {product.highlight?.arms && product.highlight.arms.length > 0 && (
              <div className="tiny">
                Purchase intent vs control:{" "}
                {product.highlight.arms.map((a, i) => (
                  <span key={a.label}>
                    {i > 0 && " · "}
                    {a.label} {signed(a.est)}
                  </span>
                ))}
              </div>
            )}
            {product.highlight?.headline && <p className="small" style={{ marginTop: 6 }}>{product.highlight.headline}</p>}
          </a>
        )}
        {base && (
          <a className="demo-card" href={simHref(`run/${base.id}`)}>
            <div className="tiny muted">Social scenario · brand crisis</div>
            <div className="list-title">{base.title}</div>
            <p className="small secondary">A product recall spreads on a simulated feed; two hours in it branches into an apology, a transparency response and a no-change control.</p>
            {branches.length > 0 && <BranchList branches={branches} />}
          </a>
        )}
      </div>
    </Card>
  );
}

function BranchList({ branches }: { branches: DemoRun[] }) {
  return (
    <div className="tiny" style={{ marginTop: 6 }}>
      Negative-emotion share after the branch:{" "}
      {branches.map((b, i) => (
        <span key={b.id}>
          {i > 0 && " · "}
          {b.title.split(" at ")[0].replace(/^Control from .*/, "No change")} {b.highlight?.ner != null ? `${Math.round(b.highlight.ner * 100)}%` : "—"}
        </span>
      ))}
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
            behavioral economist, a political scientist and a demographer. This follows Park et al. (2024), whose agents built from real people's two-hour interviews
            reproduced their General Social Survey answers 83% as well as the people themselves did two weeks later (85% in the paper's first version). Here the
            interviews are written by the model, which adds detail but not information. Every agent sees the control and every message variant, so effects are measured
            within the same people.
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
