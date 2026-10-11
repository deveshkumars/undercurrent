"""Structured-output schemas for simulation calls."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from .models import Expert


class ExpertReflections(BaseModel):
    psychologist: list[str]
    behavioral_economist: list[str]
    political_scientist: list[str]
    demographer: list[str]


class PersonaOutput(BaseModel):
    first_name: str
    identity: str = Field(description="2-3 sentence first-person self-description, like a social media bio.")
    transcript: str = Field(description="The interview transcript with 'Interviewer:' and 'Respondent:' turns.")
    reflections: ExpertReflections


class ReflectionsOutput(BaseModel):
    first_name: str = Field(description="A plausible pseudonym first name (never the respondent's real name).")
    identity: str = Field(description="2-3 sentence first-person self-description, like a social media bio.")
    reflections: ExpertReflections


class Route(BaseModel):
    question_id: str
    expert: Expert
    why: str


class RoutingOutput(BaseModel):
    routes: list[Route]


class Theme(BaseModel):
    theme: str
    arms: list[str] = Field(description="Arm labels where this theme shows up.")
    segments: list[str] = Field(description="Segments where it is most common, if any.")
    prevalence: Literal["rare", "some", "common"]
    quotes: list[str] = Field(description="1-3 verbatim quotes from the respondents.")


class ArmVerdict(BaseModel):
    arm: str
    verdict: Literal["strongest", "effective", "mixed", "ineffective", "backfires"]
    why: str


class FocusGroupSummary(BaseModel):
    headline: str = Field(description="One sentence a strategist would put at the top of the memo.")
    summary: str = Field(description="Two short paragraphs.")
    themes: list[Theme]
    arm_comparison: list[ArmVerdict]
    segment_notes: list[str]
    surprises: list[str]
    backfire_risks: list[str]
    recommended_edits: list[str]
    caveats: list[str]


def make_panel_schema(questions: list[dict], name: str = "PanelAnswers") -> type[BaseModel]:
    """One schema per run: a reasoning field, then one field per question (q_<id>).

    Bounds aren't encoded (structured outputs drop min/max); answers are clamped server-side.
    """
    fields: dict[str, Any] = {
        "reasoning": (str, Field(description="2-4 first-person sentences: what went through your mind.")),
    }
    for q in questions:
        desc = q["text"]
        if q["kind"] == "single_choice":
            typ: Any = Literal[tuple(q["options"])]  # type: ignore[valid-type]
        elif q["kind"] == "scale":
            typ = int
            desc += f" (integer {q.get('scale_min', 0)}-{q.get('scale_max', 100)})"
        else:
            typ = str
            desc += " (at most 40 words, in your own voice)"
        fields[f"q_{q['id']}"] = (typ, Field(description=desc))
    return create_model(name, **fields)  # type: ignore[call-overload]


# ---------------------------------------------------------------- social (POSIM Social-BDI, one call)

Intensity = Literal["very_low", "low", "medium", "high", "very_high"]
Motive = Literal[
    "emotional_venting", "entertainment", "self_expression", "social_approval", "social_connection",
    "justice_advocacy", "information_seeking", "influencing_others", "inform_audience", "attract_attention",
]
ActionType = Literal["like", "repost", "repost_with_comment", "short_comment", "long_comment", "short_post", "long_post"]


class Opinion(BaseModel):
    subject: str = Field(description="Who or what the opinion is about.")
    opinion: str = Field(description="One sentence, in your own words.")
    stance: float = Field(description="-1 strongly against .. 0 neutral .. +1 strongly for.")
    reason: str


class EmotionState(BaseModel):
    happy: float
    sad: float
    angry: float
    fear: float
    surprise: float
    disgust: float


class Belief(BaseModel):
    opinions: list[Opinion] = Field(description="0-3 opinions you now hold or updated after what you read.")
    emotions: EmotionState = Field(description="How you feel now, each 0-1.")


class Desire(BaseModel):
    motive: Motive
    intensity: Intensity


class Expression(BaseModel):
    emotion_type: Literal["happy", "sad", "angry", "fear", "surprise", "disgust", "neutral"]
    emotion_intensity: Literal["low", "medium", "high"]
    stance: Literal["support", "oppose", "neutral"] = Field(description="Toward the focal subject.")
    stance_intensity: Literal["low", "medium", "high"]
    style: Literal["rational", "sarcastic", "emotional", "humorous", "aggressive", "supportive", "questioning"]
    narrative: Literal["factual", "labeling", "call_to_action", "personal_story", "question", "humor", "speculation"]


class PostContent(BaseModel):
    text: str
    topics: list[str] = Field(description="0-3 hashtags without the # sign.")


class SocialAction(BaseModel):
    action_type: ActionType
    target_id: str = Field(description="A [post id] from your feed; empty for a new post.")
    expression: Expression
    content: PostContent = Field(description="Empty text for like and repost.")


class SocialActivation(BaseModel):
    perception: str = Field(description="One or two sentences: what you noticed in your feed.")
    belief: Belief
    desire: Desire
    actions: list[SocialAction] = Field(description="0-2 actions. An empty list (just scrolling) is common.")
