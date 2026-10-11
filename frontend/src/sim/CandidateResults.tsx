import { useState } from "react";
import { Card } from "../components/ui";
import { fmtDate, humanize } from "../format";
import { Scatter } from "./charts";
import { signed } from "./nav";
import type { BacktestResults, CalibrationResults, CalibrationRow, SimRun } from "./types";

const GRADE: Record<string, string> = { good: "good", fair: "warn", poor: "bad" };

function CalTable({ rows }: { rows: CalibrationRow[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Segment</th>
            <th className="num">Agents</th>
            <th className="num">Simulated</th>
            <th className="num">Polls</th>
            <th className="num">Gap</th>
            <th className="num">Opponent sim / polls</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.segment}>
              <td>
                <strong>{r.segment}</strong>
                {r.poll?.as_of && <div className="tiny muted">polls through {fmtDate(r.poll.as_of)}</div>}
              </td>
              <td className="num">{r.sim.n ?? 0}</td>
              <td className="num">{r.sim.cand != null ? `${r.sim.cand.toFixed(1)}%` : "—"}</td>
              <td className="num">{r.poll?.cand != null ? `${r.poll.cand.toFixed(1)}%` : "no polls"}</td>
              <td className={`heat ${r.diff == null ? "" : Math.abs(r.diff) < 3 ? "" : r.diff > 0 ? "pos" : "neg"}`}>{r.diff != null ? signed(r.diff) : "—"}</td>
              <td className="num tiny secondary">
                {r.sim.opp?.toFixed(1) ?? "—"} / {r.poll?.opp?.toFixed(1) ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CalibrationResultsView({ run, act }: { run: SimRun<CalibrationResults>; act: (a: "apply-calibration") => unknown }) {
  const res = run.results;
  const [busy, setBusy] = useState(false);
  if (!res) return null;
  return (
    <div className="stack">
      <Card
        title="Agents vs polls, with no message"
        sub="Each agent says who they'd vote for today. Shares exclude agents who wouldn't vote, like a poll of voters."
        actions={
          !res.applied && (
            <button
              className="btn primary sm"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await act("apply-calibration");
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Applying…" : "Apply as calibrated weights"}
            </button>
          )
        }
      >
        <div className="stack">
          <div className="row">
            <span className={`chip ${GRADE[res.grade] ?? ""}`}>average gap {res.mae != null ? `${res.mae.toFixed(1)} pts` : "—"} · {res.grade}</span>
            {res.applied && res.mae_after != null && (
              <span className="chip accent">
                after weighting {res.mae_after.toFixed(1)} pts · design effect {res.deff?.toFixed(2)}
              </span>
            )}
          </div>
          {(res.segments.find((r) => r.segment === "All")?.sim.undec ?? 0) > 50 && (
            <div className="notice warn small">
              Most agents are undecided, which usually means they don't know enough about the race. Add the candidates' parties, records and the issues people are
              hearing about to the background (in the message test's "Background every agent knows" box), then calibrate again.
            </div>
          )}
          <CalTable rows={res.segments} />
          {res.applied && res.after && (
            <>
              <div className="section-title">With calibrated weights</div>
              <CalTable rows={res.after} />
              <p className="tiny muted">
                Calibrated weights now exist for this population; pick "Calibrated to polls" when you build a message test. They fix the starting levels, not how agents
                respond to messages; a high design effect means the agents needed heavy correction.
              </p>
            </>
          )}
          {!res.applied && (
            <p className="tiny muted">
              Applying rakes a second set of weights so the simulated vote split matches the latest polling average overall and in each poll segment, alongside the
              demographic targets.
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}

export function BacktestResultsView({ run }: { run: SimRun<BacktestResults> }) {
  const res = run.results;
  if (!res) return null;
  const pts = res.events
    .filter((e) => e.sim != null && e.measured != null)
    .map((e) => ({ key: e.id, label: `${fmtDate(e.date)} · ${e.title}`, x: e.sim!, y: e.measured!, strong: e.signal === "clear" || e.signal === "strong" }));
  return (
    <div className="stack">
      <div className="tiles">
        <div className="tile">
          <div className="tile-label">Scale factor β</div>
          <div className="tile-value">{res.beta != null ? res.beta.toFixed(2) : "—"}</div>
          <div className="tile-foot">{res.beta_se != null ? `± ${res.beta_se.toFixed(2)} · poll points per simulated ${res.predictor === "vote_choice" ? "vote-share" : "thermometer"} point` : "needs 2+ events"}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Correlation</div>
          <div className="tile-value">{res.r != null ? res.r.toFixed(2) : "—"}</div>
          <div className="tile-foot">{res.r != null ? `simulated vs measured, across ${res.n_events} events` : "needs 3+ events"}</div>
        </div>
        <div className="tile">
          <div className="tile-label">Direction right</div>
          <div className="tile-value">{res.sign_agreement != null ? `${Math.round(res.sign_agreement * 100)}%` : "—"}</div>
          <div className="tile-foot">of {res.n_clear ?? 0} events with a clear measured effect</div>
        </div>
      </div>
      <Card title="Simulated vs measured movement" sub="Each dot is a past event replayed to agents with only the news up to the day before.">
        <Scatter points={pts} slope={res.beta} xLabel={res.predictor === "vote_choice" ? "Simulated change in vote share (pts)" : "Simulated change in feeling thermometer (0–100)"} yLabel="Measured change in polls (pts)" />
        <p className="tiny muted" style={{ marginTop: 6 }}>
          The thermometer is the predictor because it moves smoothly; in a low-information race most agents answer "undecided", so simulated vote share jumps one agent at a
          time. The slope converts thermometer points into poll points, and a negative or near-zero slope means the agents don't track how real voters reacted.
        </p>
      </Card>
      <Card title="Events">
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Event</th>
                <th className="num">Thermometer (sim)</th>
                <th className="num">Vote share (sim)</th>
                <th className="num">Polls (measured)</th>
                <th>Signal</th>
              </tr>
            </thead>
            <tbody>
              {res.events.map((e) => (
                <tr key={e.id}>
                  <td>
                    {e.title}
                    <div className="tiny muted">
                      {fmtDate(e.date)} · {humanize(e.type)} · {e.n} agents
                    </div>
                  </td>
                  <td className="num">
                    {signed(e.sim)} <span className="tiny muted">± {e.sim_se?.toFixed(1) ?? "—"}</span>
                  </td>
                  <td className="num">{e.sim_vote != null ? signed(e.sim_vote) : "—"}</td>
                  <td className="num">
                    {signed(e.measured)} <span className="tiny muted">± {e.measured_se?.toFixed(1) ?? "—"}</span>
                  </td>
                  <td>
                    <span className="chip">{e.signal}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
