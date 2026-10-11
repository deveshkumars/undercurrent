import { useEffect, useMemo, useState } from "react";
import { useReadOnly } from "../readOnly";
import { sim } from "../api";
import { Card, ErrorNotice, Modal } from "../components/ui";
import { MultiLine, PARTY_COLOR, armColor, type LineSeries } from "./charts";
import { goSim, signed, simHref } from "./nav";
import { RunProgress, StatusChip } from "./RunProgress";
import { InterventionEditor } from "./SocialBuilder";
import type { CompareResult, Intervention, NetworkSummary, Post, SimMeta, SimRun, SocialResults, Tick } from "./types";
import { useRunDriver } from "./useRunDriver";

const EMO_ICON: Record<string, string> = { happy: "😊", sad: "😢", angry: "😠", fear: "😨", surprise: "😮", disgust: "🤢" };

export function SocialRunView({ run, meta }: { run: SimRun<unknown>; meta: SimMeta }) {
  const readOnly = useReadOnly();
  const [ticks, setTicks] = useState<Tick[]>([]);
  const [posts, setPosts] = useState<Post[]>([]);
  const [network, setNetwork] = useState<NetworkSummary | null>(null);
  const [branches, setBranches] = useState<SimRun[]>([]);
  const [siblings, setSiblings] = useState<SimRun[]>([]);
  const [branchAt, setBranchAt] = useState<number | null>(null);
  const [thread, setThread] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // results are only filled in once the run finishes ({} before that)
  const res = run.status === "done" && run.results && "activations" in (run.results as object) ? (run.results as SocialResults) : undefined;
  const tickMin = Number(run.config.tick_minutes ?? 10);
  const every = Math.max(1, Math.round(60 / tickMin));

  useEffect(() => {
    sim.ticks(run.id).then(setTicks).catch((e) => setError((e as Error).message));
    sim.posts(run.id, { limit: 80 }).then((p) => setPosts(p.posts)).catch(() => {});
  }, [run.id, run.cursor, run.status]);
  useEffect(() => {
    sim.network(run.id).then(setNetwork).catch(() => {});
    sim.runs({ population_id: run.population_id, kind: "social" }).then((rs) => {
      setBranches(rs.filter((r) => r.parent_run_id === run.id));
      setSiblings(run.parent_run_id ? rs.filter((r) => r.parent_run_id === run.parent_run_id && r.id !== run.id && r.branch_tick === run.branch_tick) : []);
    });
  }, [run.id, run.population_id, run.parent_run_id, run.branch_tick, run.status]);

  const labels = ticks.map((t) => t.clock);
  const markers = ticks.flatMap((t, i) => (t.events.length ? [{ index: i, label: t.events.join("; ") }] : []));
  if (run.branch_tick != null) {
    const i = ticks.findIndex((t) => t.tick === run.branch_tick);
    if (i >= 0) markers.push({ index: i, label: "Branch point" });
  }
  const parties = useMemo(() => Array.from(new Set(ticks.flatMap((t) => Object.keys(t.stance_by_party ?? {})))).sort(), [ticks]);
  const totals = useMemo(() => {
    const content = ticks.reduce((a, t) => a + t.content, 0);
    const neg = ticks.reduce((a, t) => a + t.neg, 0);
    const emotional = ticks.reduce((a, t) => a + t.emotional, 0);
    return { activations: ticks.reduce((a, t) => a + t.served, 0), content, ner: emotional ? neg / emotional : null };
  }, [ticks]);
  const canBranch = !readOnly && ["done", "paused", "running", "budget_exhausted"].includes(run.status) && ticks.length > 0;

  return (
    <div className="stack">
      <ErrorNotice error={error} />
      <div className="tiles">
        <Tile label="Activations" value={(res?.activations ?? totals.activations).toLocaleString()} foot={res?.peak ? `peak at ${res.peak.clock} (${res.peak.served} in 10 min)` : `${ticks.length} of ${run.total} ticks`} />
        <Tile label="Posts & comments" value={(res ? res.posts + res.comments : totals.content).toLocaleString()} foot={res ? `${res.reposts} reposts · ${res.likes} likes` : "so far"} />
        <Tile label="Negative emotion ratio" value={res?.ner != null ? `${Math.round(res.ner * 100)}%` : totals.ner != null ? `${Math.round(totals.ner * 100)}%` : "—"} foot="share of emotional posts that are sad, angry, afraid or disgusted (POSIM's NER)" />
        <Tile label="Largest cascade" value={res ? String(res.max_cascade) : "—"} foot={res ? `posts in one thread · emotional concentration ${res.pi?.toFixed(2) ?? "—"}` : "when finished"} />
      </div>

      <Card
        title="Activity"
        sub={canBranch ? "Hawkes demand vs agents served each 10 minutes. Click any point to branch from the nearest hourly checkpoint." : "Hawkes demand vs agents served each 10 minutes."}
      >
        <MultiLine
          xLabels={labels}
          series={[
            { key: "served", label: "Agents active", color: "var(--series-1)", values: ticks.map((t) => t.served) },
            { key: "demand", label: "Demand (before the cost cap)", color: "var(--neutral-mark)", values: ticks.map((t) => t.demand), dashed: true },
          ]}
          markers={markers}
          yDomain={[0, Math.max(4, ...ticks.map((t) => Math.max(t.served, t.demand)))]}
          yFormat={(v) => (Number.isInteger(v) ? String(v) : v.toFixed(1))}
          onPick={canBranch ? (i) => setBranchAt(Math.floor(ticks[i].tick / every) * every) : undefined}
          pickLabel="Click to branch from here"
        />
      </Card>

      <div className="grid cols-2-even">
        <Card title="Negative emotion ratio" sub="Among posts this tick that carry an emotion.">
          <MultiLine xLabels={labels} series={[{ key: "ner", label: "NER", color: "var(--series-2)", values: ticks.map((t) => t.ner) }]} markers={markers} yDomain={[0, 1]} yFormat={(v) => `${Math.round(v * 100)}%`} />
        </Card>
        <Card title="Stance toward the subject, by party" sub="Mean stance (−1 against, +1 for) among agents who have formed a view.">
          <MultiLine
            xLabels={labels}
            series={parties.map((p) => ({ key: p, label: p, color: PARTY_COLOR[p] ?? "var(--neutral-mark)", values: ticks.map((t) => t.stance_by_party?.[p] ?? null) }))}
            markers={markers}
            yDomain={[-1, 1]}
            yFormat={(v) => signed(v, 1)}
            zeroLine
          />
        </Card>
      </div>

      {(siblings.length > 0 || branches.length > 0) && <BranchesCard run={run} siblings={siblings} branches={branches} />}

      <div className="grid cols-2">
        <Card title="Feed" sub="Newest first. Click a post to read its thread.">
          <div className="stack-sm" style={{ maxHeight: 640, overflow: "auto" }}>
            {posts.length === 0 && <p className="muted small">No posts yet.</p>}
            {posts.slice(0, 60).map((p) => (
              <PostCard key={p.id} p={p} onOpen={() => setThread(p.root || p.id)} />
            ))}
          </div>
        </Card>
        <div className="stack">
          {res && res.top_posts.length > 0 && (
            <Card title="Most engaged posts">
              <div className="stack-sm">
                {res.top_posts.slice(0, 5).map((p) => (
                  <PostCard key={p.id} p={p} onOpen={() => setThread(p.id)} />
                ))}
              </div>
            </Card>
          )}
          {network && (
            <Card title="Network">
              <dl className="kv">
                <dt>Accounts</dt>
                <dd>
                  {network.accounts} ({Object.entries(network.roles).map(([r, n]) => `${n} ${r.replace("_", " ")}`).join(", ")})
                </dd>
                <dt>Typical following</dt>
                <dd>{network.median_following} accounts</dd>
                <dt>Same-party follows</dt>
                <dd>{network.same_party_follow_share != null ? `${Math.round(network.same_party_follow_share * 100)}% (echo chambers)` : "—"}</dd>
              </dl>
              <div className="section-title" style={{ marginTop: 12 }}>
                Most active
              </div>
              <div className="table-wrap">
                <table className="data">
                  <tbody>
                    {network.most_active.slice(0, 8).map((a) => (
                      <tr key={a.id}>
                        <td>
                          @{a.name} <span className="tiny muted">{a.role.replace("_", " ")}{a.party ? ` · ${a.party}` : ""}</span>
                        </td>
                        <td className="num">{a.activations}×</td>
                        <td className="num">{signed(a.stance)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      </div>

      {branchAt != null && <BranchModal run={run} meta={meta} tick={branchAt} label={ticks.find((t) => t.tick === branchAt)?.clock ?? ""} onClose={() => setBranchAt(null)} />}
      {thread && <ThreadModal runId={run.id} root={thread} onClose={() => setThread(null)} />}
    </div>
  );
}

function Tile({ label, value, foot }: { label: string; value: string; foot: string }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      <div className="tile-foot">{foot}</div>
    </div>
  );
}

function PostCard({ p, onOpen }: { p: Post; onOpen?: () => void }) {
  const hh = Math.floor(p.minute / 60);
  return (
    <div className={`feed-post ${p.event ? "event" : ""}`} onClick={onOpen} style={{ cursor: onOpen ? "pointer" : undefined }}>
      <div className="meta">
        <strong style={{ color: "var(--ink)" }}>@{p.author.name}</strong>
        <span>{p.author.role === "ordinary" ? p.author.party ?? "" : p.author.role.replace("_", " ")}</span>
        <span>
          +{hh}h{String(Math.round(p.minute % 60)).padStart(2, "0")}
        </span>
        <span>{p.type.replace(/_/g, " ")}</span>
        {p.emotion && (
          <span title={`${p.emotion}, intensity ${p.intensity.toFixed(2)}`}>
            {EMO_ICON[p.emotion]} {p.emotion}
          </span>
        )}
        {p.stance !== 0 && <span>stance {signed(p.stance)}</span>}
      </div>
      <div>{p.text || <span className="muted">(repost)</span>}</div>
      {p.quoted_text && <div className="quote tiny">{p.quoted_text}</div>}
      <div className="meta">
        <span>♥ {p.likes}</span>
        <span>⟲ {p.reposts}</span>
        <span>💬 {p.comments}</span>
        {p.cascade != null && p.cascade > 1 && <span>cascade {p.cascade}</span>}
      </div>
    </div>
  );
}

function ThreadModal({ runId, root, onClose }: { runId: string; root: string; onClose: () => void }) {
  const [posts, setPosts] = useState<Post[] | null>(null);
  useEffect(() => {
    sim.posts(runId, { root }).then((r) => setPosts(r.posts));
  }, [runId, root]);
  return (
    <Modal title="Thread" onClose={onClose} width={680}>
      <div className="stack-sm">
        {posts?.map((p, i) => (
          <div key={p.id} className={i ? "reply" : ""} style={i ? { marginLeft: 14 } : undefined}>
            <PostCard p={p} />
          </div>
        ))}
      </div>
    </Modal>
  );
}

function BranchModal({ run, meta, tick, label, onClose }: { run: SimRun<unknown>; meta: SimMeta; tick: number; label: string; onClose: () => void }) {
  const tickMin = Number(run.config.tick_minutes ?? 10);
  const [items, setItems] = useState<Intervention[]>([]);
  const [title, setTitle] = useState("");
  const [withControl, setWithControl] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function create() {
    setBusy(true);
    try {
      const out = await sim.branch(run.id, { tick, title: title.trim() || (items.map((i) => i.label).filter(Boolean).join(" + ") || "Branch"), interventions: items, with_control: withControl });
      goSim(`run/${out[0].id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <Modal title={`Branch from ${label}`} onClose={onClose} width={720}>
      <div className="stack-sm">
        <p className="small secondary">
          Restarts from the checkpoint at {label} with everything that happened up to then, then adds your response. A no-change control from the same checkpoint is run too,
          so differences aren't just model randomness.
        </p>
        <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Branch name (optional)" />
        <InterventionEditor items={items} onChange={setItems} meta={meta} minMinute={tick * tickMin} />
        <label className="row small">
          <input type="checkbox" checked={withControl} onChange={(e) => setWithControl(e.target.checked)} />
          Also run a no-change control branch (recommended)
        </label>
        <ErrorNotice error={error} />
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" onClick={create} disabled={busy || !items.length}>
            {busy ? "Branching…" : "Create branch"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** Steps a sibling branch (e.g. the no-change control) from this tab so both branches advance together. */
function SiblingDriver({ id, onProgress }: { id: string; onProgress: () => void }) {
  const d = useRunDriver<unknown>(id, { onDone: onProgress, setTitle: false });
  useEffect(onProgress, [d.run?.cursor]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!d.run || d.run.status === "done") return null;
  return (
    <div className="arm-card">
      <div className="small" style={{ fontWeight: 600 }}>
        {d.run.title}
      </div>
      <RunProgress run={d.run} driving={d.driving} watching={d.watching} error={d.error} act={d.act} />
    </div>
  );
}

function BranchesCard({ run, siblings, branches }: { run: SimRun<unknown>; siblings: SimRun[]; branches: SimRun[] }) {
  const [cmp, setCmp] = useState<CompareResult | null>(null);
  const [bump, setBump] = useState(0);
  const done = siblings.filter((s) => s.status === "done").map((s) => s.id);
  useEffect(() => {
    if (!siblings.length) return;
    sim.compare(run.id, siblings.map((s) => s.id)).then(setCmp).catch(() => {});
  }, [run.id, run.status, run.cursor, bump, siblings.map((s) => s.id).join(","), done.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const labels = cmp?.runs[0]?.ticks.map((t) => t.clock) ?? [];
  const lines = (key: "ner" | "stance_mean"): LineSeries[] =>
    (cmp?.runs ?? []).map((r, i) => ({ key: r.run_id, label: r.title, color: armColor(i + 1), values: r.ticks.map((t) => t[key]), dashed: r.title.startsWith("Control") }));
  const marker = cmp ? [{ index: Math.max(0, labels.length ? cmp.runs[0].ticks.findIndex((t) => t.tick === cmp.from_tick) : 0), label: "Branch point" }] : [];
  return (
    <Card title={siblings.length ? "Compared with the other branch" : "Branches from this run"}>
      <div className="stack">
        {siblings
          .filter((sb) => !["done", "canceled", "failed"].includes(sb.status))
          .map((sb) => (
            <SiblingDriver key={sb.id} id={sb.id} onProgress={() => setBump((b) => b + 1)} />
          ))}
        {branches.length > 0 && (
          <div>
            {branches.map((b) => (
              <a key={b.id} className="list-row" href={simHref(`run/${b.id}`)}>
                <div>
                  <div className="list-title">{b.title}</div>
                  <div className="tiny muted">from tick {b.branch_tick}</div>
                </div>
                <StatusChip status={b.status} />
              </a>
            ))}
          </div>
        )}
        {cmp && (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Branch</th>
                    <th className="num">NER after branch</th>
                    <th className="num">Sentiment</th>
                    <th className="num">Final stance</th>
                    <th className="num">Posts</th>
                  </tr>
                </thead>
                <tbody>
                  {cmp.runs.map((r) => (
                    <tr key={r.run_id}>
                      <td>
                        <a href={simHref(`run/${r.run_id}`)}>{r.title}</a> <StatusChip status={r.status} />
                      </td>
                      <td className="num">{r.summary.ner != null ? `${Math.round(r.summary.ner * 100)}%` : "—"}</td>
                      <td className="num">{signed(r.summary.sentiment, 2)}</td>
                      <td className="num">{signed(r.summary.final_stance, 2)}</td>
                      <td className="num">{r.summary.content}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="grid cols-2-even">
              <div>
                <div className="section-title">Negative emotion ratio</div>
                <MultiLine xLabels={labels} series={lines("ner")} markers={marker} yDomain={[0, 1]} yFormat={(v) => `${Math.round(v * 100)}%`} height={170} />
              </div>
              <div>
                <div className="section-title">Mean stance</div>
                <MultiLine xLabels={labels} series={lines("stance_mean")} markers={marker} yDomain={[-1, 1]} yFormat={(v) => signed(v, 1)} height={170} zeroLine />
              </div>
            </div>
            <p className="tiny muted">One run per branch: treat differences smaller than run-to-run noise with care, and re-run branches to confirm a surprising result (POSIM's empathy paradox was a consistent pattern across coverage levels).</p>
          </>
        )}
      </div>
    </Card>
  );
}
