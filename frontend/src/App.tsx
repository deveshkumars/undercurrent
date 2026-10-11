import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, saveAccessCode, setUnauthorizedHandler } from "./api";
import { CandidateForm } from "./components/Forms";
import { Card, ErrorNotice, Modal, Working } from "./components/ui";
import { readSimRoute, type SimRoute } from "./sim/nav";
import { SimArea } from "./sim/SimArea";
import { ValidationView } from "./sim/ValidationView";
import { daysUntil, fmtDate, metricLabel } from "./format";
import type { Analysis, AnalysisParams, Candidate, Meta } from "./types";
import { DataView } from "./views/DataView";
import { ForecastView } from "./views/ForecastView";
import { InsightsView } from "./views/InsightsView";
import { Overview } from "./views/Overview";
import { SimulateTab } from "./views/SimulateTab";
import { StrategyView } from "./views/StrategyView";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "insights", label: "Insights" },
  { id: "forecast", label: "Forecast" },
  { id: "strategy", label: "Strategy" },
  { id: "simulate", label: "Simulate" },
  { id: "data", label: "Data" },
] as const;
type Tab = (typeof TABS)[number]["id"];

const LAST_KEY = "undercurrent.lastCandidate";

// Routes: "#/" and "#/sim/..." → Simulations (the home page); "#/validation"; "#/campaigns/<cid>/<tab>".
// Older "#/<cid>/<tab>" links are redirected into Campaigns.
type Area = "sim" | "validation" | "campaigns";

function hashParts(): string[] {
  return window.location.hash.replace(/^#\/?/, "").split("?")[0].split("/").filter(Boolean);
}

function readArea(): Area {
  const [first] = hashParts();
  if (!first || first === "sim") return "sim";
  return first === "validation" ? "validation" : "campaigns";
}

function readSim(): SimRoute {
  return readSimRoute(window.location.hash) ?? { parts: [], query: new URLSearchParams() };
}

function asTab(t: string | undefined): Tab {
  return (TABS.some((x) => x.id === t) ? t : "overview") as Tab;
}

function readHash(): { cid: string | null; tab: Tab } {
  const parts = hashParts();
  if (readArea() !== "campaigns") return { cid: null, tab: "overview" };
  const [cid, tab] = parts[0] === "campaigns" ? parts.slice(1) : parts;
  return { cid: cid || null, tab: asTab(tab) };
}

function redirectLegacy() {
  const parts = hashParts();
  if (readArea() === "campaigns" && parts[0] !== "campaigns") window.location.replace(`#/campaigns/${parts.join("/")}`);
}

function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--brand)" />
      <path d="M5 13c3.5 0 3.5-3 7-3s3.5 3 7 3 3.5-3 7-3" fill="none" stroke="var(--brand-ink)" strokeOpacity=".55" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M5 20c3.5 0 3.5-3 7-3s3.5 3 7 3 3.5-3 7-3" fill="none" stroke="var(--brand-ink)" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [needCode, setNeedCode] = useState(false);
  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [{ cid, tab }, setRoute] = useState(readHash);
  const [area, setArea] = useState<Area>(readArea);
  const [simRoute, setSimRoute] = useState<SimRoute>(readSim);
  const [params, setParams] = useState<AnalysisParams>({ metric: "vote_share", segment: "All", window_days: 14 });
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [creatingDemo, setCreatingDemo] = useState(false);

  useEffect(() => {
    setUnauthorizedHandler(() => setNeedCode(true));
    redirectLegacy();
    const onHash = () => {
      redirectLegacy();
      setArea(readArea());
      setSimRoute(readSim());
      setRoute(readHash());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = useCallback((nextCid: string | null, nextTab: Tab = "overview") => {
    window.location.hash = nextCid ? `/campaigns/${nextCid}/${nextTab}` : "/campaigns";
    setRoute({ cid: nextCid, tab: nextTab });
    setArea("campaigns");
    if (nextCid) {
      try {
        localStorage.setItem(LAST_KEY, nextCid);
      } catch {
        /* ignore */
      }
    }
  }, []);

  const loadCandidates = useCallback(async () => {
    try {
      const list = await api.candidates();
      setCandidates(list);
      setNeedCode(false);
      return list;
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) setError((e as Error).message);
      return null;
    }
  }, []);

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setError(`Can't reach the API: ${(e as Error).message}`));
    loadCandidates();
  }, [loadCandidates]);

  // pick a candidate when the URL has none, or one that no longer exists (e.g. remembered from another database)
  useEffect(() => {
    if (!candidates || area !== "campaigns") return;
    if (!candidates.length) {
      if (cid) navigate(null);
      return;
    }
    if (cid && candidates.some((c) => c.id === cid)) return;
    let last: string | null = null;
    try {
      last = localStorage.getItem(LAST_KEY);
    } catch {
      /* ignore */
    }
    navigate(candidates.find((c) => c.id === last)?.id ?? candidates[0].id, tab);
  }, [candidates, cid, tab, navigate, area]);

  const candidate = area !== "campaigns" ? null : (candidates?.find((c) => c.id === cid) ?? null);
  // only ever fetch for a candidate we know exists, never a stale id from the URL
  const activeCid = candidate?.id ?? null;

  const loadAnalysis = useCallback(async () => {
    if (!activeCid) return;
    setLoadingAnalysis(true);
    try {
      const a = await api.analysis(activeCid, params);
      setAnalysis(a);
      if (a.metric !== params.metric) setParams((p) => ({ ...p, metric: a.metric }));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingAnalysis(false);
    }
  }, [activeCid, params]);

  useEffect(() => {
    loadAnalysis();
  }, [loadAnalysis]);

  useEffect(() => {
    setAnalysis(null);
    setParams((p) => (p.segment === "All" ? p : { ...p, segment: "All" }));
  }, [activeCid]);

  const eventTitles = useMemo(() => Object.fromEntries((analysis?.events ?? []).map((e) => [e.id, e.title])), [analysis]);

  async function createDemo() {
    setCreatingDemo(true);
    try {
      const c = await api.createDemo();
      await loadCandidates();
      navigate(c.id, "overview");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreatingDemo(false);
    }
  }

  const days = candidate ? daysUntil(candidate.election_date) : null;
  const llmLabel = meta ? (meta.llm_backend === "claude-cli" ? `Claude CLI · ${meta.model}` : meta.model) : "";

  return (
    <>
      <header className="topbar">
        <a className="brand" href="#/" style={{ color: "inherit", textDecoration: "none" }}>
          <Logo />
          Undercurrent
        </a>
        <nav className="area-nav" aria-label="Sections">
          <a className={`btn sm ${area === "sim" ? "primary" : "ghost"}`} href="#/sim" aria-current={area === "sim" ? "page" : undefined}>
            Simulations
          </a>
          <a className={`btn sm ${area === "campaigns" ? "primary" : "ghost"}`} href="#/campaigns" aria-current={area === "campaigns" ? "page" : undefined}>
            Campaigns
          </a>
          <a className={`btn sm ${area === "validation" ? "primary" : "ghost"}`} href="#/validation" aria-current={area === "validation" ? "page" : undefined}>
            Validation
          </a>
        </nav>
        {area === "campaigns" && candidates && candidates.length > 0 && (
          <select className="input" style={{ width: "auto", maxWidth: 200 }} value={cid ?? ""} onChange={(e) => e.target.value && navigate(e.target.value, tab)} aria-label="Candidate">
            {candidates.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        )}
        {area === "campaigns" && (
          <button className="btn ghost sm" onClick={() => setShowNew(true)}>
            + New candidate
          </button>
        )}
        <span className="spacer" />
        {meta && (
          <span className="model-badge" title={meta.llm_ready ? "Model ready" : "No API key configured"}>
            <span className="status-dot" style={{ background: meta.llm_ready ? "var(--good)" : "var(--warn)" }} />
            {llmLabel}
          </span>
        )}
      </header>

      <main className="shell">
        {meta?.ephemeral_storage && (
          <div className="notice warn" style={{ marginBottom: 16 }}>
            No database is configured, so data on this deployment is temporary. Set MONGODB_URI to keep it.
          </div>
        )}
        {meta && !meta.llm_ready && area === "campaigns" && (
          <div className="notice warn" style={{ marginBottom: 16 }}>
            AI features are off until ANTHROPIC_API_KEY is set (or LLM_BACKEND=claude-cli for local testing). Polling analysis still works.
          </div>
        )}
        <ErrorNotice error={error} />

        {candidates === null && !needCode && !error && <Working label="Loading…" />}

        {area === "sim" && candidates && <SimArea route={simRoute} candidates={candidates} />}
        {area === "validation" && candidates && <ValidationView />}

        {area === "campaigns" && candidates && candidates.length === 0 && (
          <Card>
            <div className="empty">
              <h2>Campaign analysis</h2>
              <p style={{ maxWidth: 560, margin: "0 auto" }}>
                For campaigns: line up a candidate's polling with what they said and did, see which events moved the numbers, forecast how a new speech or interview
                will land, and get a plan for what to do next.
              </p>
              <div className="row" style={{ justifyContent: "center", marginTop: 20 }}>
                <button className="btn primary" onClick={() => setShowNew(true)}>
                  Add a candidate
                </button>
                <button className="btn" onClick={createDemo} disabled={creatingDemo}>
                  {creatingDemo ? "Loading…" : "Explore a demo campaign"}
                </button>
              </div>
              <p className="tiny muted" style={{ marginTop: 14 }}>
                The demo is a fictional race with synthetic polls.
              </p>
            </div>
          </Card>
        )}

        {candidate && (
          <>
            <div className="cand-header">
              <div>
                <h1>{candidate.name}</h1>
                <div className="cand-sub small">
                  {[candidate.office, candidate.jurisdiction, candidate.party].filter(Boolean).join(" · ")}
                  {candidate.opponent_name && <span className="dot-sep">vs {candidate.opponent_name}</span>}
                  {days != null && days >= 0 && (
                    <span className="dot-sep">
                      Election {fmtDate(candidate.election_date)} · {days} days
                    </span>
                  )}
                  {candidate.is_demo && <span className="chip accent">demo data</span>}
                </div>
              </div>
              {candidates && candidates.length > 0 && !candidates.some((c) => c.is_demo) && (
                <button className="btn ghost sm" onClick={createDemo} disabled={creatingDemo}>
                  {creatingDemo ? "Loading…" : "Load demo campaign"}
                </button>
              )}
            </div>

            <nav className="tabs" role="tablist">
              {TABS.map((t) => (
                <button key={t.id} role="tab" className="tab" aria-selected={tab === t.id} onClick={() => navigate(candidate.id, t.id)}>
                  {t.label}
                </button>
              ))}
            </nav>

            {tab !== "data" && tab !== "simulate" && analysis && (
              <div className="filters">
                <label>
                  Metric
                  <select className="input" value={params.metric} onChange={(e) => setParams({ ...params, metric: e.target.value })}>
                    {(analysis.dimensions.metrics.length ? analysis.dimensions.metrics : [params.metric]).map((m) => (
                      <option key={m} value={m}>
                        {metricLabel(m)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Segment
                  <select className="input" value={params.segment} onChange={(e) => setParams({ ...params, segment: e.target.value })}>
                    {(analysis.dimensions.segments.length ? analysis.dimensions.segments : ["All"]).map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Event window
                  <select className="input" value={params.window_days} onChange={(e) => setParams({ ...params, window_days: Number(e.target.value) })}>
                    {[7, 10, 14, 21, 30].map((d) => (
                      <option key={d} value={d}>
                        {d} days before / after
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}

            <div className={loadingAnalysis && analysis ? "refetching" : ""}>
              {tab === "overview" && (analysis ? <Overview candidate={candidate} analysis={analysis} onGoToData={() => navigate(candidate.id, "data")} /> : <Working label="Crunching the polls…" />)}
              {tab === "insights" && <InsightsView candidate={candidate} params={params} eventTitles={eventTitles} />}
              {tab === "forecast" && <ForecastView candidate={candidate} params={params} eventTitles={eventTitles} />}
              {tab === "strategy" && <StrategyView candidate={candidate} params={params} eventTitles={eventTitles} />}
              {tab === "simulate" && <SimulateTab candidate={candidate} />}
              {tab === "data" && (
                <DataView
                  candidate={candidate}
                  metric={params.metric}
                  segment={params.segment}
                  onChanged={() => {
                    loadAnalysis();
                    loadCandidates();
                  }}
                  onCandidateSaved={() => loadCandidates()}
                  onCandidateDeleted={async () => {
                    const list = await loadCandidates();
                    navigate(list?.[0]?.id ?? null);
                  }}
                />
              )}
            </div>
          </>
        )}
      </main>

      {showNew && (
        <CandidateForm
          onClose={() => setShowNew(false)}
          onSaved={async (c) => {
            setShowNew(false);
            await loadCandidates();
            navigate(c.id, "data");
          }}
        />
      )}
      {needCode && <AccessGate onUnlocked={() => loadCandidates()} />}
    </>
  );
}

function AccessGate({ onUnlocked }: { onUnlocked: () => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    saveAccessCode(code.trim());
    try {
      await api.checkAuth();
      onUnlocked();
    } catch {
      setError("That code didn't work.");
    }
  }
  return (
    <Modal title="Enter access code" onClose={() => {}}>
      <form onSubmit={submit} className="stack-sm">
        <p className="small secondary">This deployment is private. Ask the owner for the access code.</p>
        <input className="input" type="password" autoComplete="current-password" value={code} onChange={(e) => setCode(e.target.value)} />
        <ErrorNotice error={error} />
        <div className="modal-actions">
          <button className="btn primary" type="submit" disabled={!code.trim()}>
            Unlock
          </button>
        </div>
      </form>
    </Modal>
  );
}
