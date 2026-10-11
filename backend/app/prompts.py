"""Prompt text and the candidate dossier the model reasons over."""

from __future__ import annotations

from datetime import date
from typing import Any

SYSTEM_PROMPT = """You are Undercurrent, an analyst for political campaigns. You study how a candidate's \
actions and statements line up with movement in their polling, forecast how planned appearances will land, \
and give strategic recommendations.

How you work:
- Ground every claim in the dossier: the polling average, measured event impacts, segment crosstabs, and the \
content of what the candidate actually said. Quote the candidate's own words when explaining why something worked \
or backfired. In prose, name events by a short title and date (e.g. "the May 9 housing debate"); use the bracketed \
event ids only in fields that ask for an event id.
- Measured impacts are correlational. Treat "none" and "weak" signals as noise unless several events point the \
same way, say when overlapping events make attribution ambiguous, and never present one noisy delta as proof.
- Keep numbers consistent with the measured history. A single event rarely moves a topline average by more than \
3 points; segment effects are larger but noisier.
- Be candid. A campaign gains nothing from flattery: if a line or tactic is likely to backfire, say so and explain why.
- Recommend only what an ethical campaign can do: persuasion, message discipline, policy communication, \
scheduling, outreach and organizing. Never recommend deception, disinformation, voter suppression, or \
fabricated attacks; if asked, decline that part and offer a legitimate alternative.
- Stay nonpartisan: judge what moves voters toward or away from this candidate, not whether their positions are right."""

SIGNAL_NOTE = (
    "Signal labels: strong |z|>=2.58, clear |z|>=1.96, weak |z|>=1.28, none below that, "
    "insufficient = fewer than 2 polls on one side of the event."
)


def _fmt(x: Any, signed: bool = False, nd: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.{nd}f}" if signed else f"{x:.{nd}f}"


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_dossier(candidate: dict, analysis: dict, today: date | None = None) -> str:
    today = today or date.today()
    s = analysis["stats"]
    lines: list[str] = []
    add = lines.append

    add("# Candidate")
    add(f"Name: {candidate['name']}")
    for label, key in (("Office", "office"), ("Party", "party"), ("Jurisdiction", "jurisdiction"), ("Opponent", "opponent_name")):
        if candidate.get(key):
            add(f"{label}: {candidate[key]}")
    if candidate.get("election_date"):
        days = (date.fromisoformat(str(candidate["election_date"])) - today).days
        add(f"Election date: {candidate['election_date']} ({days} days from today, {today.isoformat()})")
    else:
        add(f"Today: {today.isoformat()}")
    if candidate.get("bio"):
        add(f"Background: {_clip(candidate['bio'], 1500)}")

    add("")
    add(f"# Polling — metric: {analysis['metric']}, segment: {analysis['segment']}")
    if not s.get("poll_count"):
        add("No polls for this metric/segment yet.")
    else:
        add(
            f"Current average {_fmt(s['latest'])}% as of {s['latest_date']} (±{_fmt((s.get('latest_se') or 0) * 1.96)}). "
            f"7-day change {_fmt(s.get('change_7d'), True)} pp; 30-day change {_fmt(s.get('change_30d'), True)} pp."
        )
        if s.get("opponent_latest") is not None:
            add(
                f"Opponent average {_fmt(s['opponent_latest'])}%; margin {_fmt(s.get('margin'), True)} pp "
                f"(30-day margin change {_fmt(s.get('margin_change_30d'), True)} pp)."
            )
        add(
            f"Range since {s['first_date']}: high {_fmt(s['high']['value'])}% ({s['high']['date']}), "
            f"low {_fmt(s['low']['value'])}% ({s['low']['date']}). Typical 14-day swing ±{_fmt(s.get('volatility_14d'))} pp. "
            f"{s['poll_count']} polls from {s['pollster_count']} pollsters."
        )
        add("")
        add("Weekly polling average (house-effect adjusted):")
        add("date | candidate | opponent")
        trend = analysis["trend"]
        for row in trend[::7] + ([trend[-1]] if (len(trend) - 1) % 7 else []):
            add(f"{row['date']} | {_fmt(row.get('value'))} | {_fmt(row.get('opp'))}")
        if analysis.get("house_effects"):
            add("Pollster house effects (pp, already removed): " + ", ".join(
                f"{h['pollster']} {_fmt(h['effect'], True)} (n={h['n']})" for h in analysis["house_effects"]
            ))

    add("")
    add(f"# Events with measured impact (window: {analysis['window_days']} days before vs after)")
    add("Delta = house-adjusted mean of polls after the event minus before, in pp. " + SIGNAL_NOTE)
    for ev in analysis["events"]:
        imp = ev.get("impact") or {}
        add("")
        add(f"[{ev['id']}] {ev['date']} · {ev['type']} · {ev['title']}")
        meta = []
        if ev.get("venue"):
            meta.append(f"venue: {ev['venue']}")
        if ev.get("audience"):
            meta.append(f"audience: {ev['audience']}")
        if ev.get("topics"):
            meta.append("topics: " + ", ".join(ev["topics"]))
        if ev.get("tone"):
            meta.append(f"tone: {ev['tone']}")
        if meta:
            add("  " + "; ".join(meta))
        if ev.get("summary"):
            add(f"  Summary: {_clip(ev['summary'], 600)}")
        if ev.get("content"):
            add("  Content: " + _clip(ev["content"], 1400).replace("\n", "\n    "))
        add(
            f"  Measured: delta {_fmt(imp.get('delta'), True)} pp (se {_fmt(imp.get('se'))}, z {_fmt(imp.get('z'), True)}, "
            f"signal {imp.get('signal')}; {imp.get('n_pre', 0)} polls before / {imp.get('n_post', 0)} after)"
        )
        if ev.get("segment_impacts"):
            add("  Segments: " + "; ".join(
                f"{seg} {_fmt(v['delta'], True)} (z {_fmt(v['z'], True)}, {v['signal']})" for seg, v in ev["segment_impacts"].items()
            ))
        if ev.get("overlaps"):
            add("  Overlaps with: " + ", ".join(f"[{o['id']}] {o['title']}" for o in ev["overlaps"]))

    if analysis.get("themes"):
        add("")
        add("# Pooled effect by topic (inverse-variance mean of event deltas)")
        for t in analysis["themes"]:
            add(f"{t['label']}: {_fmt(t['mean_delta'], True)} pp (se {_fmt(t['se'])}, {t['count']} events)")
    if analysis.get("event_types"):
        add("")
        add("# Pooled effect by event type")
        for t in analysis["event_types"]:
            add(f"{t['label']}: {_fmt(t['mean_delta'], True)} pp (se {_fmt(t['se'])}, {t['count']} events)")
    return "\n".join(lines)


def insights_task(focus: str) -> str:
    extra = f"\nThe campaign specifically asked: {focus.strip()}\n" if focus.strip() else ""
    return f"""Task: write an analysis of how this candidate's actions and statements line up with their polling.{extra}
Cover the overall trajectory and what drove it; the events with the clearest positive and negative effects and \
why they landed that way (what was said, tone, audience, timing); which themes and event types help or hurt; how \
segments differ; recurring patterns in the candidate's language that track with gains or losses; and risks \
visible in the data. Include only events with a real signal as key drivers, unless a pattern across several weak \
events is itself the point. Put methodological limits in caveats."""


def features_task(draft: dict, vocabulary: list[str]) -> str:
    return f"""Task: read this planned {draft['type']} and describe it so it can be matched against past events.
Reuse these existing topic names where they fit: {", ".join(vocabulary) or "(none yet)"}. Add a new topic only if none fit.

Title: {draft['title']}
Venue: {draft.get('venue') or 'n/a'}
Audience: {draft.get('audience') or 'n/a'}
<draft>
{draft['content']}
</draft>"""


def forecast_task(draft: dict, features: dict, prior: dict, segments: list[str]) -> str:
    analog_lines = "\n".join(
        f"- [{a['id']}] {a['date']} {a['type']} '{a['title']}' similarity {a['similarity']}: "
        f"delta {_fmt(a['delta'], True)} pp (se {_fmt(a['se'])}, {a['signal']})"
        for a in prior["analogs"]
    ) or "- none similar enough"
    return f"""Task: forecast how this planned {draft['type']} will move the candidate's polling and how it will be received.

Title: {draft['title']}
Planned date: {draft.get('planned_date') or 'unspecified'}
Venue: {draft.get('venue') or 'n/a'}
Audience: {draft.get('audience') or 'n/a'}
<draft>
{draft['content']}
</draft>

Extracted features: topics {features['topics']}; tone {features['tone']}; primary message: {features['primary_message']}

Statistical prior from the most similar past events (shrunk toward zero):
expected {_fmt(prior['prior_mean'], True)} pp, sd {_fmt(prior['prior_sd'])}, 80% range {_fmt(prior['range_80'][0], True)} to {_fmt(prior['range_80'][1], True)} pp.
Analogs:
{analog_lines}

Start from that prior and move away from it only for reasons you can point to in the draft: specific lines, tone, \
audience fit, or contrast with what worked or failed before. Give a segment reaction for each of these segments \
where you can: {", ".join(segments) or "the topline only"}. Assess the draft's most consequential lines verbatim, \
both strengths and risks, with rewrites for the risks. List concrete changes that would improve the expected effect."""


def recommendations_task(goal: str, latest_insight_headline: str | None) -> str:
    goal_line = f"The campaign's stated goal: {goal.strip()}" if goal.strip() else "No specific goal was given; optimize for winning the race."
    prior = f"\nThe most recent analysis concluded: {latest_insight_headline}" if latest_insight_headline else ""
    return f"""Task: recommend a strategy for the rest of the campaign.
{goal_line}{prior}

Base every priority on evidence from the dossier and list the ids of the events it rests on. Say which messages to amplify, \
which to drop or reframe (with the reframe), which event formats to do more or less of, and what to do in the next \
30 days given the election date. Prefer fewer, sharper priorities over a long list."""


def tag_task(title: str, summary: str, content: str, vocabulary: list[str]) -> str:
    return f"""Task: tag this campaign event. Reuse these existing topic names where they fit: {", ".join(vocabulary) or "(none yet)"}.
Use 1-4 short lowercase topics. Tone is one or two words.

Title: {title}
Summary: {summary or 'n/a'}
<content>
{content or 'n/a'}
</content>"""
