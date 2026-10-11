// Mirrors backend/app/sim (models.py, routes.py and the results each run kind produces).

export type Expert = "psychologist" | "behavioral_economist" | "political_scientist" | "demographer";
export type RunKind = "populate" | "panel" | "calibration" | "backtest" | "social";
export type RunStatus = "pending" | "running" | "paused" | "finalizing" | "done" | "failed" | "canceled" | "budget_exhausted";
export type Margins = Record<string, Record<string, number>>;

export interface Question {
  id: string;
  text: string;
  kind: "single_choice" | "scale" | "open";
  options: string[];
  scale_min: number;
  scale_max: number;
  scale_labels: string[];
  ordinal?: boolean;
  primary?: boolean;
  expert?: Expert | null;
  builtin?: boolean;
}

export interface InterventionTemplate {
  id: string;
  label: string;
  description: string;
  interventions: (Omit<Intervention, "at_minute" | "id" | "label"> & { offset_min: number })[];
}

export interface SimMeta {
  enabled: boolean;
  model: string;
  backend: string;
  llm_ready: boolean;
  presets: Record<string, { label: string; description: string; margins: Margins }>;
  levels: Record<string, string[]>;
  labels: Record<string, string>;
  level_labels: Record<string, string>;
  targetable: string[];
  questionnaires: Record<string, Question[]>;
  formats: Record<string, string>;
  experts: Record<string, string>;
  intervention_templates: InterventionTemplate[];
  limits: { max_agents: number; max_social_agents: number; max_calls_per_run: number; concurrency: number };
  pricing: { input: number; output: number };
}

export interface Estimate {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  usd: number;
  minutes: number;
  model: string;
  backend: string;
  billing: string;
}

export interface MarginCell {
  target: number | null;
  weighted: number;
  raw: number;
}

export interface Weighting {
  converged: boolean;
  iterations: number;
  max_error?: number;
  margins: Record<string, Record<string, MarginCell>>;
  deff: number;
  n_eff: number;
  trimmed: number;
  warnings: string[];
}

export interface PopulationInput {
  name: string;
  description: string;
  size: number;
  preset: string;
  targets: Margins;
  oversample: Margins;
  persona_mode: "interview" | "demographic";
  card_detail: "light" | "full";
  transcript_words: number;
  reflections_per_expert: number;
  geography: string;
  candidate_id: string | null;
  seed?: number | null;
}

export interface Population extends PopulationInput {
  id: string;
  created_at: string;
  source: "synthetic" | "csv";
  status: "draft" | "generating" | "ready" | "failed";
  agent_count: number;
  ready_count: number;
  weighting: Weighting;
  summary: { n?: number; deff?: number; n_eff?: number; median_age?: number | null; max_weight?: number; min_weight?: number };
  calibration: { candidate_id: string; run_id: string; mae: number | null; grade: string; applied: boolean; mae_after?: number | null; deff?: number } | null;
  backtest: { candidate_id: string; run_id: string; beta: number | null; beta_se: number | null; r: number | null; sign_agreement: number | null; n_events: number } | null;
  populate_run_id: string | null;
  populate_run?: { id: string; status: RunStatus; cursor: number; total: number; progress: Progress; error: string } | null;
  import?: { mode: string; chunks: number; rows: number; pii_dropped: string[]; mapping: Record<string, string>; unknown_values: Record<string, Record<string, number>> };
}

export interface Demographics {
  age?: number | null;
  age_band?: string | null;
  gender?: string | null;
  race?: string | null;
  education?: string | null;
  income?: string | null;
  region?: string | null;
  state?: string;
  urbanicity?: string | null;
  party?: string | null;
  lean?: string | null;
  ideology?: string | null;
  vote_2024?: string | null;
  turnout?: number | null;
}

export interface Traits {
  big5: Record<string, number>;
  occupation: string;
  household: string;
  religion: string;
  news_diet: string[];
  salient_issues: string[];
  social_media_use: string;
  psych_type: string;
  activity: number;
  baseline_emotion: Record<string, number>;
}

export interface PanelResponse {
  id: string;
  run_id: string;
  agent_id: string;
  arm_id: string;
  replicate: number;
  status: "ok" | "error";
  reasoning: string;
  answers: Record<string, string | number | null>;
  error: string;
  event_id?: string;
  run_title?: string;
}

export interface Agent {
  id: string;
  population_id: string;
  index: number;
  source: "synthetic" | "csv_survey" | "csv_interview";
  external_id: string;
  demographics: Demographics;
  traits: Traits;
  base_weight: number;
  weight: number;
  weight_cal: number | null;
  persona_status: "pending" | "ready" | "failed";
  persona_error: string;
  first_name: string;
  identity: string;
  transcript?: string;
  raw?: Record<string, string>;
  reflections?: Record<Expert, string[]> | null;
  responses?: PanelResponse[];
}

export interface Progress {
  done: number;
  failed: number;
  calls: number;
  usd: number;
  avg_batch_s: number | null;
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
}

export interface Arm {
  id: string;
  label: string;
  kind: "control" | "treatment";
  control_mode?: "placebo" | "none";
  format?: string;
  source?: string;
  text?: string;
  source_event_id?: string | null;
}

export interface SimRun<R = Record<string, unknown>> {
  id: string;
  kind: RunKind;
  population_id: string;
  candidate_id: string | null;
  parent_run_id: string | null;
  branch_tick?: number | null;
  title: string;
  config: Record<string, unknown> & { n_agents?: number };
  created_at: string;
  updated_at: string;
  status: RunStatus;
  cursor: number;
  total: number;
  retry?: number[];
  lease_owner?: string | null;
  concurrency?: number;
  progress: Progress;
  estimate: Estimate;
  budget?: { max_calls: number };
  log?: string[];
  error: string;
  results?: R;
  model?: string;
}

export interface EffectCell {
  est: number | null;
  lo: number | null;
  hi: number | null;
  se?: number | null;
  p?: number | null;
  n: number;
}

export interface SegmentCell {
  treatment: string;
  dim: string;
  level: string;
  est: number | null;
  lo: number | null;
  hi: number | null;
  se: number | null;
  p: number | null;
  n: number;
  n_eff: number;
  control_mean: number | null;
  small: boolean;
  fdr: boolean;
}

export interface Quote {
  agent_id: string;
  arm_id: string;
  arm: string;
  name: string;
  who: string;
  delta: number | null;
  texts: Record<string, string>;
  reasoning: string;
}

export interface FocusGroupSummary {
  headline: string;
  summary: string;
  themes: { theme: string; arms: string[]; segments: string[]; prevalence: "rare" | "some" | "common"; quotes: string[] }[];
  arm_comparison: { arm: string; verdict: "strongest" | "effective" | "mixed" | "ineffective" | "backfires"; why: string }[];
  segment_notes: string[];
  surprises: string[];
  backfire_risks: string[];
  recommended_edits: string[];
  caveats: string[];
}

export interface Topline {
  mean?: number | null;
  sd?: number | null;
  n?: number;
  hist?: (number | null)[];
  shares?: Record<string, number | null>;
}

export interface PanelResults {
  n_agents: number;
  n_responses: number;
  n_errors: number;
  n_eff: number;
  weight_set: string;
  primary: string | null;
  toplines: Record<string, Record<string, Topline>>;
  effects: Record<string, Record<string, EffectCell & { options?: Record<string, EffectCell> }>>;
  segments: SegmentCell[];
  vote_segments: SegmentCell[];
  transitions: Record<string, Record<string, Record<string, number | null>>>;
  quotes: Quote[];
  unmapped_poll_segments: string[];
  sources: string[];
  summary: FocusGroupSummary | null;
  summary_error?: string;
  backtest_adjusted?: { beta: number; beta_se: number; r: number | null; run_id: string; predictor?: string; effects: Record<string, { est: number | null; lo: number | null; hi: number | null; raw: number }> };
}

export interface Split {
  cand?: number | null;
  opp?: number | null;
  undec?: number | null;
  se?: number | null;
  n?: number;
  n_eff?: number;
  as_of?: string;
  polls?: number;
}

export interface CalibrationRow {
  segment: string;
  sim: Split;
  poll: Split | null;
  diff?: number;
  z?: number | null;
  diff_opp?: number;
}

export interface CalibrationResults {
  segments: CalibrationRow[];
  mae: number | null;
  grade: string;
  n_agents: number;
  applied: boolean;
  after?: CalibrationRow[];
  mae_after?: number | null;
  deff?: number;
  applied_segments?: string[];
}

export interface BacktestEvent {
  id: string;
  title: string;
  date: string;
  type: string;
  sim: number | null;
  sim_se: number | null;
  sim_vote?: number | null;
  sim_vote_se?: number | null;
  n: number;
  measured: number | null;
  measured_se: number | null;
  signal: string;
  segments: Record<string, { sim: number | null; sim_se: number | null; n: number; measured: number | null; measured_signal: string | null }>;
}

export interface BacktestResults {
  events: BacktestEvent[];
  beta: number | null;
  beta_se: number | null;
  r: number | null;
  sign_agreement: number | null;
  n_clear?: number;
  n_events: number;
  n_agents: number;
  predictor?: string;
}

export interface Intervention {
  id?: string;
  at_minute: number;
  kind: "event" | "node_control" | "platform_policy";
  label?: string;
  event?: { author: string; text: string; topics?: string[]; importance?: number } | null;
  node_control?: { selector: { role?: string; party?: string; fraction?: number }; action: "prime" | "post" | "mute"; text?: string; duration_min?: number } | null;
  platform_policy?: Record<string, number> | null;
}

export interface Tick {
  tick: number;
  minute: number;
  clock: string;
  lambda: number;
  demand: number;
  served: number;
  failed: number;
  actions: Record<string, number>;
  content: number;
  sentiment: number | null;
  neg: number;
  emotional: number;
  ner: number | null;
  pi: number | null;
  stance_mean: number | null;
  stance_by_party: Record<string, number | null>;
  sp: number | null;
  with_opinion: number;
  mood: Record<string, number>;
  events: string[];
}

export interface Post {
  id: string;
  type: string;
  minute: number;
  text: string;
  topics: string[];
  emotion: string | null;
  intensity: number;
  stance: number;
  style: string | null;
  narrative: string | null;
  likes: number;
  reposts: number;
  comments: number;
  parent: string | null;
  root: string;
  event?: boolean;
  quoted_text?: string;
  cascade?: number;
  author: { id: string; name: string; role: string; party: string | null };
}

export interface SocialResults {
  activations: number;
  demand: number;
  posts: number;
  comments: number;
  reposts: number;
  likes: number;
  ner: number | null;
  sentiment: number | null;
  pi: number | null;
  emotions: Record<string, number>;
  stance_by_party: Record<string, number | null>;
  with_opinion: number;
  cascades: Record<string, number>;
  max_cascade: number;
  peak: { clock: string; served: number } | null;
  top_posts: Post[];
}

export interface NetworkSummary {
  accounts: number;
  roles: Record<string, number>;
  median_following: number;
  same_party_follow_share: number | null;
  top_accounts: { id: string; name: string; role: string; party: string | null; followers: number }[];
  most_active: { id: string; name: string; role: string; party: string | null; activations: number; stance: number }[];
}

export interface CompareResult {
  from_tick: number;
  runs: {
    run_id: string;
    title: string;
    status: RunStatus;
    ticks: Pick<Tick, "tick" | "clock" | "served" | "ner" | "sentiment" | "stance_mean" | "sp" | "content">[];
    summary: { ner: number | null; sentiment: number | null; final_stance: number | null; content: number; activations: number };
    delta_vs_last: { ner: number | null; sentiment: number | null; final_stance: number | null };
  }[];
}

export interface CandidateSimHub {
  runs: SimRun[];
  populations: Population[];
  poll_segments: string[];
  eligible_events: { id: string; date: string; title: string; type: string; delta: number; signal: string }[];
}

export interface SegmentMapping {
  segments: { segment: string; agents: number; weighted_share: number }[];
  unmapped: string[];
  suggested_targets: Record<string, number>;
}
