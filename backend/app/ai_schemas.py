"""Pydantic schemas the model must fill (sent as structured-output JSON schemas)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["low", "medium", "high"]


# ---------- insights ----------


class Driver(BaseModel):
    event_id: str = Field(description="The [id] of the event from the dossier.")
    title: str
    direction: Literal["positive", "negative", "mixed"]
    measured_delta_pp: float = Field(description="Copy the measured topline delta for this event from the dossier.")
    confidence: Confidence = Field(description="How confident you are this event caused the movement.")
    why_it_landed: str = Field(description="What about the content, tone, audience or timing explains the reaction.")
    key_quote: str = Field(description="The candidate's own words that best illustrate it, or empty.")


class ThemeInsight(BaseModel):
    theme: str
    verdict: Literal["helps", "hurts", "neutral", "unclear"]
    explanation: str


class SegmentInsight(BaseModel):
    segment: str
    observation: str


class LanguagePattern(BaseModel):
    pattern: str = Field(description="A recurring way the candidate talks, e.g. 'specific dollar figures'.")
    effect: Literal["helps", "hurts", "mixed"]
    example_quote: str
    example_event_id: str


class InsightsOutput(BaseModel):
    headline: str = Field(description="One sentence a campaign manager would put at the top of a memo.")
    summary: str = Field(description="Two or three short paragraphs.")
    trajectory: str = Field(description="How the average moved over time and the main inflection points.")
    key_drivers: list[Driver]
    themes: list[ThemeInsight]
    segments: list[SegmentInsight]
    language_patterns: list[LanguagePattern]
    risks: list[str]
    caveats: list[str]


# ---------- forecast ----------


class DraftFeatures(BaseModel):
    topics: list[str] = Field(description="Topics, reusing the campaign's existing topic names where they fit.")
    tone: str = Field(description="One or two words, e.g. 'optimistic', 'combative', 'empathetic'.")
    primary_message: str
    key_claims: list[str]
    audiences: list[str] = Field(description="Voter groups the draft is aimed at or likely to reach.")


class SegmentReaction(BaseModel):
    segment: str
    reaction: Literal["positive", "negative", "mixed", "neutral"]
    effect_pp: float
    reasoning: str


class LineAssessment(BaseModel):
    quote: str = Field(description="A verbatim line from the draft.")
    assessment: Literal["strength", "risk"]
    why: str
    suggested_rewrite: str = Field(description="A better version of the line for risks; empty for strengths.")


class ForecastOutput(BaseModel):
    headline: str
    verdict: Literal["likely_gain", "likely_neutral", "likely_loss", "high_variance"]
    predicted_effect_pp: float = Field(description="Expected change in the polling average, in percentage points.")
    low_pp: float = Field(description="Low end of an 80% range.")
    high_pp: float = Field(description="High end of an 80% range.")
    confidence: Confidence
    reasoning: str = Field(description="How you combined the historical prior, analog events and the draft itself.")
    reception_summary: str
    segment_reactions: list[SegmentReaction]
    line_assessments: list[LineAssessment]
    likely_headlines: list[str]
    opponent_attack_lines: list[str]
    recommended_changes: list[str]


# ---------- recommendations ----------


class Priority(BaseModel):
    title: str
    rationale: str
    actions: list[str]
    target_segments: list[str]
    expected_impact: Literal["high", "medium", "low"]
    evidence_event_ids: list[str]


class MessageAdvice(BaseModel):
    message: str
    evidence: str


class ReframeAdvice(BaseModel):
    message: str
    problem: str
    reframe: str


class FormatAdvice(BaseModel):
    event_type: str
    advice: str


class RecommendationsOutput(BaseModel):
    strategic_summary: str
    priorities: list[Priority]
    amplify: list[MessageAdvice]
    avoid_or_reframe: list[ReframeAdvice]
    format_strategy: list[FormatAdvice]
    next_30_days: list[str]
    metrics_to_watch: list[str]


# ---------- event tagging ----------


class EventTags(BaseModel):
    topics: list[str]
    tone: str
    summary: str = Field(description="One or two sentences describing what happened.")
