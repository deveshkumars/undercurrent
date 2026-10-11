"""Domain models for candidates, polls, events and saved AI reports."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
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
]

EVENT_TYPES: tuple[str, ...] = EventType.__args__  # type: ignore[attr-defined]


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- Candidates ----------


class CandidateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    office: str = Field(default="", max_length=160)
    party: str = Field(default="", max_length=80)
    jurisdiction: str = Field(default="", max_length=120)
    opponent_name: str = Field(default="", max_length=120)
    election_date: date | None = None
    bio: str = Field(default="", max_length=4000)


class CandidatePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    office: str | None = None
    party: str | None = None
    jurisdiction: str | None = None
    opponent_name: str | None = None
    election_date: date | None = None
    bio: str | None = None


class Candidate(CandidateIn):
    id: str = Field(default_factory=new_id)
    created_at: str = Field(default_factory=utcnow)
    is_demo: bool = False


# ---------- Polls ----------


class PollIn(BaseModel):
    date: date  # last day in the field
    pollster: str = Field(default="Unknown", max_length=120)
    sample_size: int | None = Field(default=None, ge=1, le=1_000_000)
    population: str = Field(default="", max_length=20)  # LV / RV / A
    metric: str = Field(default="vote_share", max_length=60)
    segment: str = Field(default="All", max_length=80)
    value: float = Field(ge=0, le=100)  # candidate's share, in percent
    opponent_value: float | None = Field(default=None, ge=0, le=100)
    margin_of_error: float | None = Field(default=None, ge=0, le=50)


class Poll(PollIn):
    id: str = Field(default_factory=new_id)
    candidate_id: str


# ---------- Events (actions, statements, appearances) ----------


class EventIn(BaseModel):
    date: date
    type: EventType = "statement"
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=4000)
    content: str = Field(default="", max_length=60_000)  # transcript excerpt, quotes, ad script...
    topics: list[str] = Field(default_factory=list)
    tone: str = Field(default="", max_length=40)
    venue: str = Field(default="", max_length=200)
    audience: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=500)


class Event(EventIn):
    id: str = Field(default_factory=new_id)
    candidate_id: str


# ---------- Requests for AI features ----------


class AnalysisParams(BaseModel):
    metric: str = "vote_share"
    segment: str = "All"
    window_days: int = Field(default=14, ge=3, le=60)


class InsightsRequest(AnalysisParams):
    focus: str = Field(default="", max_length=1000)


class ForecastRequest(AnalysisParams):
    title: str = Field(min_length=1, max_length=200)
    type: EventType = "speech"
    planned_date: date | None = None
    venue: str = Field(default="", max_length=200)
    audience: str = Field(default="", max_length=200)
    content: str = Field(min_length=20, max_length=60_000)


class RecommendationsRequest(AnalysisParams):
    goal: str = Field(default="", max_length=1000)


class TagEventRequest(BaseModel):
    title: str = ""
    summary: str = ""
    content: str = ""
    existing_topics: list[str] = Field(default_factory=list)


class CsvImport(BaseModel):
    csv: str = Field(min_length=1, max_length=2_000_000)
    replace: bool = False


class Report(BaseModel):
    id: str = Field(default_factory=new_id)
    candidate_id: str
    kind: Literal["insights", "forecast", "recommendations"]
    created_at: str = Field(default_factory=utcnow)
    model: str
    params: dict[str, Any]
    quant: dict[str, Any] = Field(default_factory=dict)  # deterministic numbers the AI was given
    output: dict[str, Any]
