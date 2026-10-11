import type {
  Analysis,
  AnalysisParams,
  CampaignEvent,
  Candidate,
  CandidateInput,
  EventInput,
  ForecastReport,
  InsightsReport,
  Meta,
  Poll,
  PollInput,
  RecommendationsReport,
  Report,
} from "./types";
import type {
  Agent,
  CandidateSimHub,
  CompareResult,
  Estimate,
  Intervention,
  NetworkSummary,
  PanelResponse,
  Population,
  PopulationInput,
  Post,
  Question,
  SegmentMapping,
  SimMeta,
  SimRun,
  Tick,
  ValidationResults,
  Weighting,
} from "./sim/types";

const CODE_KEY = "undercurrent.accessCode";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function readCode(): string {
  try {
    return localStorage.getItem(CODE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveAccessCode(code: string) {
  try {
    localStorage.setItem(CODE_KEY, code);
  } catch {
    /* storage unavailable: the code lasts for this page view only */
  }
  memoryCode = code;
}

let memoryCode = readCode();
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (memoryCode) headers["x-access-code"] = memoryCode;
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail))
        message = data.detail.map((d: { loc?: string[]; msg: string }) => `${d.loc?.slice(1).join(".")}: ${d.msg}`).join("; ");
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401) onUnauthorized?.();
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

const q = (p: AnalysisParams) =>
  `metric=${encodeURIComponent(p.metric)}&segment=${encodeURIComponent(p.segment)}&window_days=${p.window_days}`;

export interface ImportResult {
  imported: number;
  errors: { row: number; error: string }[];
  error_count: number;
  ignored_columns: string[];
}

export const api = {
  meta: () => request<Meta>("GET", "/meta"),
  validation: () => request<ValidationResults>("GET", "/validation"),
  checkAuth: () => request<{ ok: boolean }>("GET", "/auth/check"),

  candidates: () => request<Candidate[]>("GET", "/candidates"),
  createCandidate: (c: CandidateInput) => request<Candidate>("POST", "/candidates", c),
  createDemo: () => request<Candidate>("POST", "/candidates/demo"),
  updateCandidate: (id: string, c: Partial<CandidateInput>) => request<Candidate>("PATCH", `/candidates/${id}`, c),
  deleteCandidate: (id: string) => request<{ deleted: boolean }>("DELETE", `/candidates/${id}`),

  polls: (cid: string) => request<Poll[]>("GET", `/candidates/${cid}/polls`),
  addPoll: (cid: string, p: PollInput) => request<Poll>("POST", `/candidates/${cid}/polls`, p),
  deletePoll: (cid: string, pid: string) => request<{ deleted: boolean }>("DELETE", `/candidates/${cid}/polls/${pid}`),
  importPolls: (cid: string, csv: string, replace: boolean) =>
    request<ImportResult>("POST", `/candidates/${cid}/polls/import`, { csv, replace }),

  events: (cid: string) => request<CampaignEvent[]>("GET", `/candidates/${cid}/events`),
  addEvent: (cid: string, e: EventInput) => request<CampaignEvent>("POST", `/candidates/${cid}/events`, e),
  updateEvent: (cid: string, eid: string, e: EventInput) => request<CampaignEvent>("PUT", `/candidates/${cid}/events/${eid}`, e),
  deleteEvent: (cid: string, eid: string) => request<{ deleted: boolean }>("DELETE", `/candidates/${cid}/events/${eid}`),
  importEvents: (cid: string, csv: string, replace: boolean) =>
    request<ImportResult>("POST", `/candidates/${cid}/events/import`, { csv, replace }),
  tagEvent: (cid: string, e: { title: string; summary: string; content: string; existing_topics: string[] }) =>
    request<{ topics: string[]; tone: string; summary: string }>("POST", `/candidates/${cid}/events/tag`, e),

  analysis: (cid: string, p: AnalysisParams) => request<Analysis>("GET", `/candidates/${cid}/analysis?${q(p)}`),

  insights: (cid: string, p: AnalysisParams & { focus: string }) => request<InsightsReport>("POST", `/candidates/${cid}/insights`, p),
  forecast: (
    cid: string,
    p: AnalysisParams & { title: string; type: string; planned_date: string | null; venue: string; audience: string; content: string },
  ) => request<ForecastReport>("POST", `/candidates/${cid}/forecast`, p),
  recommendations: (cid: string, p: AnalysisParams & { goal: string }) =>
    request<RecommendationsReport>("POST", `/candidates/${cid}/recommendations`, p),
  reports: <R extends Report>(cid: string, kind: string) => request<R[]>("GET", `/candidates/${cid}/reports?kind=${kind}`),
  deleteReport: (cid: string, rid: string) => request<{ deleted: boolean }>("DELETE", `/candidates/${cid}/reports/${rid}`),
};

/** Download a protected file (the access code travels as a header, so a plain link won't do). */
export async function downloadFile(path: string, filename: string) {
  const headers: Record<string, string> = {};
  if (memoryCode) headers["x-access-code"] = memoryCode;
  const res = await fetch(`/api${path}`, { headers });
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText}`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface PanelInput {
  population_id: string;
  candidate_id: string | null;
  title: string;
  subject: string;
  opponent: string;
  context: string;
  arms: { id: string; label: string; kind: "control" | "treatment"; control_mode?: string; format?: string; source?: string; text?: string; source_event_id?: string | null }[];
  questionnaire: string;
  questions: Question[];
  sample_size: number | null;
  replicates: number;
  weight_set: "demographic" | "calibrated";
  likely_voter: boolean;
  source_report_id?: string | null;
}

export interface SocialInput {
  population_id: string;
  candidate_id: string | null;
  title: string;
  focal_subject: string;
  context: string;
  seed_event: Intervention;
  n_agents: number;
  duration_hours: number;
  tick_minutes: number;
  start_clock: string;
  max_calls_per_tick: number;
  interventions: Intervention[];
}

export interface ImportChunkResult {
  imported: number;
  total: number;
  columns: { mapping: Record<string, string>; pii_dropped: string[]; answer_columns: string[] };
  unknown_values: Record<string, Record<string, number>>;
}

const qs = (o: Record<string, string | number | null | undefined>) =>
  Object.entries(o)
    .filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join("&");

export const sim = {
  meta: () => request<SimMeta>("GET", "/sim/meta"),
  estimate: (kind: string, config: Record<string, unknown>) => request<Estimate>("POST", "/sim/estimate", { kind, config }),

  previewPopulation: (p: PopulationInput) =>
    request<{ weighting: Weighting; summary: Population["summary"]; estimate: Estimate }>("POST", "/sim/populations/preview", p),
  createPopulation: (p: PopulationInput) => request<Population>("POST", "/sim/populations", p),
  populations: (candidateId?: string) => request<Population[]>("GET", `/sim/populations?${qs({ candidate_id: candidateId })}`),
  population: (pid: string) => request<Population>("GET", `/sim/populations/${pid}`),
  updatePopulation: (pid: string, p: { name?: string; description?: string; candidate_id?: string | null }) =>
    request<Population>("PATCH", `/sim/populations/${pid}`, p),
  deletePopulation: (pid: string) => request<{ deleted: boolean }>("DELETE", `/sim/populations/${pid}`),
  reweight: (pid: string, targets: Record<string, Record<string, number>>) => request<Population>("POST", `/sim/populations/${pid}/reweight`, { targets }),
  importStart: (b: { name: string; description: string; mode: string; consent_attested: boolean; card_detail: string; geography: string; candidate_id: string | null }) =>
    request<Population>("POST", "/sim/populations/import", b),
  importChunk: (pid: string, csv: string) => request<ImportChunkResult>("POST", `/sim/populations/${pid}/import/chunk`, { csv }),
  importFinish: (pid: string, b: { rake: boolean; preset: string; generate_reflections: boolean }) =>
    request<Population>("POST", `/sim/populations/${pid}/import/finish`, b),
  agents: (pid: string, offset = 0, limit = 50) =>
    request<{ total: number; agents: Agent[] }>("GET", `/sim/populations/${pid}/agents?${qs({ offset, limit })}`),
  agent: (aid: string) => request<Agent>("GET", `/sim/agents/${aid}`),

  createPanel: (p: PanelInput) => request<SimRun>("POST", "/sim/runs/panel", p),
  createSocial: (p: SocialInput) => request<SimRun>("POST", "/sim/runs/social", p),
  runs: (f: { population_id?: string; candidate_id?: string; kind?: string } = {}) => request<SimRun[]>("GET", `/sim/runs?${qs(f)}`),
  run: <R>(rid: string) => request<SimRun<R>>("GET", `/sim/runs/${rid}`),
  updateRun: (rid: string, p: { title?: string; max_calls?: number }) => request<SimRun>("PATCH", `/sim/runs/${rid}`, p),
  deleteRun: (rid: string) => request<{ deleted: boolean }>("DELETE", `/sim/runs/${rid}`),
  step: <R>(rid: string) => request<SimRun<R>>("POST", `/sim/runs/${rid}/step`),
  control: <R>(rid: string, action: "pause" | "resume" | "cancel" | "retry-failed" | "summarize" | "recompute" | "apply-calibration") =>
    request<SimRun<R>>("POST", `/sim/runs/${rid}/${action}`),
  responses: (rid: string, f: { arm?: string; agent?: string; offset?: number; limit?: number } = {}) =>
    request<{ total: number; responses: PanelResponse[] }>("GET", `/sim/runs/${rid}/responses?${qs(f)}`),
  ticks: (rid: string) => request<Tick[]>("GET", `/sim/runs/${rid}/ticks`),
  posts: (rid: string, f: { root?: string; author?: string; limit?: number } = {}) =>
    request<{ total?: number; posts: Post[] }>("GET", `/sim/runs/${rid}/posts?${qs(f)}`),
  network: (rid: string) => request<NetworkSummary>("GET", `/sim/runs/${rid}/network`),
  branch: (rid: string, b: { tick: number; title: string; interventions: Intervention[]; with_control: boolean }) =>
    request<SimRun[]>("POST", `/sim/runs/${rid}/branch`, b),
  compare: (rid: string, others: string[]) => request<CompareResult>("GET", `/sim/runs/${rid}/compare?${qs({ with: others.join(",") })}`),

  candidateHub: (cid: string) => request<CandidateSimHub>("GET", `/candidates/${cid}/sim`),
  candidateContext: (cid: string, asOf?: string) => request<{ context: string }>("GET", `/candidates/${cid}/sim/context?${qs({ as_of: asOf })}`),
  candidateSegments: (cid: string, pid: string) => request<SegmentMapping>("GET", `/candidates/${cid}/sim/segments?${qs({ population_id: pid })}`),
  calibrate: (cid: string, b: { population_id: string; sample_size?: number | null; context?: string | null }) =>
    request<SimRun>("POST", `/candidates/${cid}/sim/calibration`, b),
  backtest: (cid: string, b: { population_id: string; event_ids: string[]; sample_size: number }) =>
    request<SimRun>("POST", `/candidates/${cid}/sim/backtest`, b),
};
