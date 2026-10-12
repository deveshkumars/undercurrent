"""Request models and stored-document shapes for simulations."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Expert = Literal["psychologist", "behavioral_economist", "political_scientist", "demographer"]
EXPERTS: tuple[str, ...] = Expert.__args__  # type: ignore[attr-defined]
PsychType = Literal["curiosity_seeking", "self_actualization", "bandwagon", "cathartic_venting", "anti_authority"]
Preset = Literal["us_adults", "us_registered_voters", "us_likely_voters"]
# Schema ceiling on agent counts; the configured limit (SIM_MAX_AGENTS, default 500) is enforced when a
# population or run is created, so deployments can raise it (e.g. 1,000 for the benchmark) without a code change.
HARD_MAX_AGENTS = 10_000
RunKind = Literal["populate", "panel", "calibration", "backtest", "social", "survey"]
RunStatus = Literal["pending", "running", "paused", "finalizing", "done", "failed", "canceled", "budget_exhausted"]
StimulusFormat = Literal[
    "news_article", "ad_script", "speech_excerpt", "social_post", "debate_clip",
    "policy_summary", "product_description", "email", "other",
]


# ---------------------------------------------------------------- populations


class PopulationIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    size: int = Field(default=100, ge=10, le=HARD_MAX_AGENTS)
    preset: Preset = "us_registered_voters"
    # {variable: {level: share}} overriding preset margins, e.g. a district's partisan mix
    targets: dict[str, dict[str, float]] = Field(default_factory=dict)
    # {variable: {level: factor}}: draw more of a group; base weights undo it
    oversample: dict[str, dict[str, float]] = Field(default_factory=dict)
    # interview = LLM-written life-history interview + expert reflections (Park et al.);
    # demographic = card only, no LLM calls (Park's weaker "demographics-only" baseline)
    persona_mode: Literal["interview", "demographic"] = "interview"
    # light = no party/ideology labels in the agent prompt (reduces stereotyping); full = all labels
    card_detail: Literal["light", "full"] = "light"
    transcript_words: int = Field(default=900, ge=300, le=3000)
    reflections_per_expert: int = Field(default=6, ge=3, le=20)
    geography: str = Field(default="", max_length=200)  # e.g. "Pennsylvania" or "Lakeshore State (fictional)"
    candidate_id: str | None = None
    seed: int | None = None

    @field_validator("targets", "oversample")
    @classmethod
    def _non_negative(cls, v: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
        for var, levels in v.items():
            if any(x < 0 for x in levels.values()):
                raise ValueError(f"{var}: shares and factors must be non-negative")
        return v


class PopulationPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    candidate_id: str | None = None


class ReweightIn(BaseModel):
    targets: dict[str, dict[str, float]] = Field(default_factory=dict)


class ImportStart(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    mode: Literal["auto", "survey", "interview"] = "auto"
    consent_attested: bool = False
    card_detail: Literal["light", "full"] = "light"
    reflections_per_expert: int = Field(default=6, ge=3, le=20)
    geography: str = Field(default="", max_length=200)
    candidate_id: str | None = None


class ImportChunk(BaseModel):
    csv: str = Field(min_length=1, max_length=3_200_000)


class ImportFinish(BaseModel):
    rake: bool = True
    preset: Preset = "us_registered_voters"
    targets: dict[str, dict[str, float]] = Field(default_factory=dict)
    generate_reflections: bool = True


# ---------------------------------------------------------------- panel


class Question(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    text: str = Field(min_length=3, max_length=600)
    kind: Literal["single_choice", "scale", "open"]
    options: list[str] = Field(default_factory=list)
    scale_min: int = 0
    scale_max: int = 100
    scale_labels: list[str] = Field(default_factory=list)
    ordinal: bool = False  # options run from most positive to most negative; also scored 0-100
    primary: bool = False
    expert: Expert | None = None
    builtin: bool = False

    @model_validator(mode="after")
    def _check(self) -> "Question":
        if self.kind == "single_choice":
            opts = [o.strip() for o in self.options if o.strip()]
            if not 2 <= len(opts) <= 10 or len(set(opts)) != len(opts):
                raise ValueError(f"question {self.id}: give 2-10 distinct options")
            self.options = opts
        if self.kind == "scale" and self.scale_max <= self.scale_min:
            raise ValueError(f"question {self.id}: scale_max must exceed scale_min")
        return self


class Arm(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{1,24}$")
    label: str = Field(min_length=1, max_length=80)
    kind: Literal["control", "treatment"]
    control_mode: Literal["placebo", "none"] = "placebo"
    format: StimulusFormat = "other"
    source: str = Field(default="", max_length=120)  # e.g. "the Riverton Gazette", "a TV ad"
    text: str = Field(default="", max_length=20_000)
    source_event_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "Arm":
        if self.kind == "treatment" and len(self.text.strip()) < 10:
            raise ValueError(f"arm {self.label}: paste the message (at least 10 characters)")
        return self


class PanelIn(BaseModel):
    population_id: str
    candidate_id: str | None = None
    title: str = Field(min_length=1, max_length=160)
    subject: str = Field(default="", max_length=160)  # who/what is evaluated (candidate, product, policy)
    opponent: str = Field(default="", max_length=160)
    context: str = Field(default="", max_length=8_000)  # background every agent knows
    arms: list[Arm]
    questionnaire: Literal["political", "product", "policy", "custom"] = "political"
    questions: list[Question] = Field(default_factory=list)  # custom questions (added to the preset's)
    sample_size: int | None = Field(default=None, ge=5, le=HARD_MAX_AGENTS)
    replicates: int = Field(default=1, ge=1, le=3)
    weight_set: Literal["demographic", "calibrated"] = "demographic"
    likely_voter: bool = False
    seed: int | None = None
    source_report_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "PanelIn":
        controls = [a for a in self.arms if a.kind == "control"]
        treatments = [a for a in self.arms if a.kind == "treatment"]
        if len(controls) != 1:
            raise ValueError("a panel needs exactly one control arm")
        if not 1 <= len(treatments) <= 4:
            raise ValueError("a panel needs 1-4 treatment arms")
        if len({a.id for a in self.arms}) != len(self.arms):
            raise ValueError("arm ids must be unique")
        return self


class SurveyQuestion(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    text: str = Field(min_length=3, max_length=1500)
    options: list[str] = Field(min_length=2, max_length=12)


class SurveyBlockIn(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]{1,24}$")
    questions: list[SurveyQuestion] = Field(min_length=1, max_length=20)


class SurveyIn(BaseModel):
    """A closed-ended questionnaire asked in blocks, one call per agent per block (validation runs)."""

    population_id: str
    title: str = Field(min_length=1, max_length=160)
    blocks: list[SurveyBlockIn] = Field(min_length=1, max_length=60)
    # interview = the agent as the app builds it; card = card only; demographics = attributes only
    persona_style: Literal["interview", "card", "demographics"] = "interview"
    preamble: str = Field(default="", max_length=1000)
    sample_size: int | None = Field(default=None, ge=5, le=HARD_MAX_AGENTS)
    seed: int | None = None

    @model_validator(mode="after")
    def _check(self) -> "SurveyIn":
        sizes = {len(b.questions) for b in self.blocks}
        if len(sizes) != 1:
            raise ValueError("every block needs the same number of questions (one output schema per run)")
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("block ids must be unique")
        keys = [q.id for b in self.blocks for q in b.questions]
        if len(set(keys)) != len(keys):
            raise ValueError("question ids must be unique")
        return self


class CalibrationIn(BaseModel):
    population_id: str
    sample_size: int | None = Field(default=None, ge=5, le=HARD_MAX_AGENTS)
    context: str | None = Field(default=None, max_length=8_000)


class BacktestIn(BaseModel):
    population_id: str
    event_ids: list[str] = Field(default_factory=list)
    sample_size: int = Field(default=60, ge=5, le=300)


class RunPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    max_calls: int | None = Field(default=None, ge=1, le=100_000)


# ---------------------------------------------------------------- social


class Intervention(BaseModel):
    id: str = Field(default="", max_length=40)
    at_minute: int = Field(ge=0, le=72 * 60)
    kind: Literal["event", "node_control", "platform_policy"]
    label: str = Field(default="", max_length=120)
    # event: {author, text, topics, importance 0.5-3}
    event: dict[str, Any] | None = None
    # node_control: {selector: {role?, party?, ideology?, fraction?}, action: prime|post|mute, text, duration_min}
    node_control: dict[str, Any] | None = None
    # platform_policy: any of {w_h, w_p, w_r, r_explore, k}
    platform_policy: dict[str, float] | None = None


class SocialIn(BaseModel):
    population_id: str
    candidate_id: str | None = None
    title: str = Field(min_length=1, max_length=160)
    focal_subject: str = Field(min_length=1, max_length=160)  # what stances are about
    context: str = Field(default="", max_length=6_000)
    seed_event: Intervention
    n_agents: int = Field(default=60, ge=10, le=200)
    duration_hours: int = Field(default=12, ge=1, le=72)
    tick_minutes: int = Field(default=10, ge=5, le=60)
    start_clock: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    max_calls_per_tick: int = Field(default=12, ge=1, le=60)
    interventions: list[Intervention] = Field(default_factory=list)
    hawkes: dict[str, float] = Field(default_factory=dict)
    feed: dict[str, float] = Field(default_factory=dict)
    emotion: dict[str, float] = Field(default_factory=dict)
    seed: int | None = None


class BranchIn(BaseModel):
    tick: int = Field(ge=0)
    title: str = Field(default="", max_length=160)
    interventions: list[Intervention] = Field(default_factory=list)
    with_control: bool = True


class EstimateIn(BaseModel):
    kind: Literal["populate", "panel", "social"]
    config: dict[str, Any]
