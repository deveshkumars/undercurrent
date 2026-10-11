import { useState } from "react";
import { sim } from "../api";
import { Spinner } from "../components/ui";
import type { SimRun } from "./types";

const STATUS: Record<string, { label: string; chip: string }> = {
  pending: { label: "Queued", chip: "" },
  running: { label: "Running", chip: "accent" },
  finalizing: { label: "Analyzing", chip: "accent" },
  paused: { label: "Paused", chip: "warn" },
  budget_exhausted: { label: "Hit call budget", chip: "warn" },
  done: { label: "Done", chip: "good" },
  failed: { label: "Failed", chip: "bad" },
  canceled: { label: "Canceled", chip: "" },
};

export function StatusChip({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, chip: "" };
  return <span className={`chip ${s.chip}`}>{s.label}</span>;
}

export function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v < 0.01) return v === 0 ? "$0" : "<$0.01";
  return `$${v.toFixed(v < 1 ? 3 : 2)}`;
}

export function fmtMinutes(m: number): string {
  if (m < 1) return "under a minute";
  if (m < 90) return `~${Math.round(m)} min`;
  return `~${(m / 60).toFixed(1)} h`;
}

export function EstimateLine({ est }: { est: { calls: number; usd: number; minutes: number; billing: string; model: string } }) {
  return (
    <span className="small secondary">
      {est.calls.toLocaleString()} model calls · {est.billing.startsWith("subscription") ? "uses your Claude login" : fmtUsd(est.usd)} · {fmtMinutes(est.minutes)} · {est.model}
    </span>
  );
}

const UNIT: Record<string, string> = { populate: "agents", panel: "agents", calibration: "agents", backtest: "agent × event", social: "ticks" };

type Act = (a: "pause" | "resume" | "cancel" | "retry-failed") => unknown;

export function RunProgress({ run, driving, watching, error, act, onChanged }: {
  run: SimRun<unknown>;
  driving: boolean;
  watching: boolean;
  error: string | null;
  act: Act;
  onChanged?: (run: SimRun<unknown>) => void;
}) {
  const [raising, setRaising] = useState(false);
  const pct = run.total ? Math.min(100, (100 * run.cursor) / run.total) : 0;
  const p = run.progress;
  const conc = run.concurrency || 1;
  const eta = p.avg_batch_s && run.cursor < run.total ? (((run.total - run.cursor) / conc) * p.avg_batch_s) / 60 : null;
  const active = ["pending", "running", "finalizing"].includes(run.status);
  const cli = run.estimate?.billing?.startsWith("subscription");

  async function raiseBudget() {
    setRaising(true);
    try {
      const next = Math.max((run.budget?.max_calls ?? 0) * 2, (run.budget?.max_calls ?? 0) + 200);
      onChanged?.(await sim.updateRun(run.id, { max_calls: next }));
      await act("resume");
    } finally {
      setRaising(false);
    }
  }

  return (
    <div className="run-progress">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row">
          <StatusChip status={run.status} />
          {driving && run.status !== "finalizing" && (
            <span className="small secondary">
              <Spinner /> {run.cursor.toLocaleString()} of {run.total.toLocaleString()} {UNIT[run.kind]}
              {eta != null && ` · about ${eta < 1 ? "<1" : Math.round(eta)} min left`}
            </span>
          )}
          {driving && run.status === "finalizing" && (
            <span className="small secondary">
              <Spinner /> Crunching results{run.kind === "panel" ? " and writing the debrief" : ""}…
            </span>
          )}
          {watching && <span className="small muted">Another tab is running this; watching.</span>}
        </div>
        <div className="row">
          {active && driving && (
            <button className="btn sm" onClick={() => act("pause")}>
              Pause
            </button>
          )}
          {(run.status === "paused" || (active && !driving)) && (
            <button className="btn sm primary" onClick={() => act("resume")}>
              Resume
            </button>
          )}
          {run.status === "budget_exhausted" && (
            <button className="btn sm primary" onClick={raiseBudget} disabled={raising}>
              Raise budget & continue
            </button>
          )}
          {p.failed > 0 && ["done", "paused", "budget_exhausted"].includes(run.status) && run.kind !== "social" && (
            <button className="btn sm" onClick={() => act("retry-failed")}>
              Retry {p.failed} failed
            </button>
          )}
          {(active || run.status === "paused" || run.status === "budget_exhausted") && (
            <button className="btn ghost sm danger" onClick={() => confirm("Cancel this run? Results so far are kept.") && act("cancel")}>
              Cancel
            </button>
          )}
        </div>
      </div>
      {run.status !== "done" && (
        <div className="progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
          <div style={{ width: `${pct}%` }} />
        </div>
      )}
      <div className="tiny muted">
        {p.calls.toLocaleString()} calls{run.budget ? ` of ${run.budget.max_calls.toLocaleString()} budget` : ""} ·{" "}
        {(p.input_tokens + p.cache_read_input_tokens + p.cache_creation_input_tokens).toLocaleString()} in / {p.output_tokens.toLocaleString()} out tokens
        {p.cache_read_input_tokens > 0 && ` (${Math.round((100 * p.cache_read_input_tokens) / Math.max(1, p.input_tokens + p.cache_read_input_tokens + p.cache_creation_input_tokens))}% from cache)`}
        {" · "}
        {cli ? "billed to your Claude login" : `${fmtUsd(p.usd)} so far (est. ${fmtUsd(run.estimate?.usd)})`}
        {p.failed > 0 && ` · ${p.failed} failed`}
      </div>
      {(error || run.error) && <div className="notice error small">{error || run.error}</div>}
      {run.log && run.log.length > 0 && (
        <details>
          <summary className="tiny muted" style={{ cursor: "pointer" }}>
            Run log
          </summary>
          <pre className="run-log">{run.log.slice(-12).join("\n")}</pre>
        </details>
      )}
    </div>
  );
}
