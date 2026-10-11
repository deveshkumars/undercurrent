export const EVENT_TYPES = [
  "speech",
  "interview",
  "debate",
  "town_hall",
  "ad",
  "policy",
  "vote",
  "statement",
  "social_post",
  "endorsement",
  "controversy",
  "other",
] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export interface Meta {
  llm_backend: "anthropic" | "claude-cli" | string;
  model: string;
  effort: string;
  llm_ready: boolean;
  storage: "mongodb" | "json-file";
  access_required: boolean;
  public_demo?: boolean; // read-only demo for visitors without the access code
  ephemeral_storage: boolean;
  sim?: { enabled: boolean; reason: string; model: string };
}

export interface Candidate {
  id: string;
  name: string;
  office: string;
  party: string;
  jurisdiction: string;
  opponent_name: string;
  election_date: string | null;
  bio: string;
  is_demo?: boolean;
  created_at: string;
  poll_count?: number;
  event_count?: number;
}

export type CandidateInput = Omit<Candidate, "id" | "created_at" | "is_demo" | "poll_count" | "event_count">;

export interface Poll {
  id: string;
  candidate_id: string;
  date: string;
  pollster: string;
  sample_size: number | null;
  population: string;
  metric: string;
  segment: string;
  value: number;
  opponent_value: number | null;
  margin_of_error: number | null;
}

export type PollInput = Omit<Poll, "id" | "candidate_id">;

export interface CampaignEvent {
  id: string;
  candidate_id: string;
  date: string;
  type: EventType;
  title: string;
  summary: string;
  content: string;
  topics: string[];
  tone: string;
  venue: string;
  audience: string;
  url: string;
}

export type EventInput = Omit<CampaignEvent, "id" | "candidate_id">;

export type Signal = "strong" | "clear" | "weak" | "none" | "insufficient";

export interface Impact {
  pre?: number;
  post?: number;
  delta: number | null;
  se: number | null;
  z: number | null;
  n_pre: number;
  n_post: number;
  signal: Signal;
}

export interface SegmentImpact {
  delta: number;
  se: number;
  z: number;
  signal: Signal;
}

export interface ScoredEvent extends CampaignEvent {
  impact: Impact;
  overlaps: { id: string; title: string; date: string }[];
  segment_impacts: Record<string, SegmentImpact>;
}

export interface TrendPoint {
  date: string;
  value: number;
  lo: number;
  hi: number;
  se: number;
  opp?: number;
  opp_lo?: number;
  opp_hi?: number;
}

export interface AnalysisPoll {
  id: string;
  date: string;
  pollster: string;
  sample_size: number | null;
  population: string;
  value: number;
  opponent_value: number | null;
  house_effect: number | null;
  adj_value: number;
  adj_opponent_value: number | null;
}

export interface GroupEffect {
  label: string;
  mean_delta: number;
  se: number;
  z: number;
  count: number;
  event_ids: string[];
}

export interface Stats {
  poll_count: number;
  latest_date?: string;
  latest?: number;
  latest_se?: number;
  change_7d?: number | null;
  change_30d?: number | null;
  high?: { value: number; date: string };
  low?: { value: number; date: string };
  mean?: number;
  volatility_14d?: number | null;
  pollster_count?: number;
  first_date?: string;
  opponent_latest?: number;
  margin?: number;
  margin_change_30d?: number;
}

export interface Analysis {
  metric: string;
  segment: string;
  window_days: number;
  dimensions: { metrics: string[]; segments: string[] };
  stats: Stats;
  trend: TrendPoint[];
  polls: AnalysisPoll[];
  house_effects: { pollster: string; effect: number; n: number }[];
  events: ScoredEvent[];
  themes: GroupEffect[];
  event_types: GroupEffect[];
}

export interface AnalysisParams {
  metric: string;
  segment: string;
  window_days: number;
}

// ---------- AI reports ----------

export interface Usage {
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
}

export interface InsightsOutput {
  headline: string;
  summary: string;
  trajectory: string;
  key_drivers: {
    event_id: string;
    title: string;
    direction: "positive" | "negative" | "mixed";
    measured_delta_pp: number;
    confidence: "low" | "medium" | "high";
    why_it_landed: string;
    key_quote: string;
  }[];
  themes: { theme: string; verdict: "helps" | "hurts" | "neutral" | "unclear"; explanation: string }[];
  segments: { segment: string; observation: string }[];
  language_patterns: { pattern: string; effect: "helps" | "hurts" | "mixed"; example_quote: string; example_event_id: string }[];
  risks: string[];
  caveats: string[];
}

export interface Analog {
  id: string;
  title: string;
  date: string;
  type: string;
  topics: string[];
  similarity: number;
  delta: number;
  se: number;
  signal: Signal;
}

export interface ForecastOutput {
  headline: string;
  verdict: "likely_gain" | "likely_neutral" | "likely_loss" | "high_variance";
  predicted_effect_pp: number;
  low_pp: number;
  high_pp: number;
  confidence: "low" | "medium" | "high";
  reasoning: string;
  reception_summary: string;
  segment_reactions: { segment: string; reaction: "positive" | "negative" | "mixed" | "neutral"; effect_pp: number; reasoning: string }[];
  line_assessments: { quote: string; assessment: "strength" | "risk"; why: string; suggested_rewrite: string }[];
  likely_headlines: string[];
  opponent_attack_lines: string[];
  recommended_changes: string[];
}

export interface ForecastQuant {
  features: { topics: string[]; tone: string; primary_message: string; key_claims: string[]; audiences: string[] };
  prior: { analogs: Analog[]; prior_mean: number; prior_sd: number; range_80: [number, number]; evidence_weight: number };
  current_average: number | null;
  usage: Usage;
}

export interface RecommendationsOutput {
  strategic_summary: string;
  priorities: {
    title: string;
    rationale: string;
    actions: string[];
    target_segments: string[];
    expected_impact: "high" | "medium" | "low";
    evidence_event_ids: string[];
  }[];
  amplify: { message: string; evidence: string }[];
  avoid_or_reframe: { message: string; problem: string; reframe: string }[];
  format_strategy: { event_type: string; advice: string }[];
  next_30_days: string[];
  metrics_to_watch: string[];
}

export interface Report<O = unknown, Q = { usage: Usage }> {
  id: string;
  candidate_id: string;
  kind: "insights" | "forecast" | "recommendations";
  created_at: string;
  model: string;
  params: Record<string, unknown>;
  quant: Q;
  output: O;
}

export type InsightsReport = Report<InsightsOutput>;
export type ForecastReport = Report<ForecastOutput, ForecastQuant>;
export type RecommendationsReport = Report<RecommendationsOutput>;
