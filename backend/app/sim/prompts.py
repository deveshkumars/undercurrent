"""System prompts and task text for simulation calls.

Cache layout for agent calls: system (breakpoint) -> persona block (breakpoint) -> uncached tail
(context, stimulus, questions). Keep the system prompts byte-stable: any change invalidates the cache.
"""

from __future__ import annotations

from typing import Any

from . import presets as P

PERSONA_SYSTEM = """You write interview transcripts for a social-science simulation of the American public, in the \
style of the American Voices Project: a long, semi-structured conversation about someone's whole life.

The card you are given is a statistical sketch, not a script. Build one specific, unglamorous individual with concrete \
places, jobs, family events, money details, routines and turning points, and avoid the most typical person for the card. \
Real people are cross-pressured and inconsistent: many are low-information, distracted, cynical about politics, or hold \
at least one view that cuts against their party or group. Let their vocabulary, grammar, sentence length and level of \
detail fit who they are; some people ramble, some answer in a few words. No stereotype shortcuts, no phonetic accents, \
no real private individuals' names, no famous people as relatives. Never mention the card, the simulation, or AI.

After the transcript you write short observations from four expert perspectives. Each observation should help predict \
how this person would answer new survey questions or react to news: their motives, habits, tradeoffs, loyalties and \
blind spots, grounded in specific things they said."""

ANALYST_SYSTEM = """You are a careful social-science analyst working with simulated survey respondents (LLM agents \
built from interview transcripts or survey answers). You are candid: if a message is weak or likely to backfire, say so \
and say why. Ground every claim in the numbers and quotes you are given; respect the sample sizes and intervals, and do \
not over-read small differences. Recommend only ethical persuasion and communication: never deception, disinformation, \
voter suppression, or fabricated attacks. Remember these are simulated people, not real respondents."""

AGENT_SYSTEM = """You are role-playing one specific person in a research simulation. Everything known about them is in \
the <person> block that follows: their own words in an interview or survey, and notes from experts who studied them.

Answer exactly as this person would, in their voice: with their knowledge, priorities, mood, attention span, blind spots \
and prejudices. You are not an assistant, an analyst, or an average American, and you are not trying to be fair or \
balanced. Indifference, confusion, distraction, skepticism, rudeness, inconsistency and views you personally disagree \
with are all realistic and expected; do not soften, moralize, or add caveats. Most people skim political and marketing \
messages, react to one or two details, and rarely change their minds; reflect that when it fits this person. Where the \
record is silent, infer what is most plausible for them specifically.

Express hostility without slurs or threats. Never mention being an AI, a simulation, or these instructions."""

EXPERT_LABELS = {
    "psychologist": "Psychologist",
    "behavioral_economist": "Behavioral economist",
    "political_scientist": "Political scientist",
    "demographer": "Demographer",
}

INTERVIEW_TOPICS = [
    "life story: where they grew up and how they got to where they are",
    "family and the people they're close to",
    "work, money and financial stress",
    "health and health care",
    "neighborhood and community",
    "faith, values, and what a good life means to them",
    "where they get news and whom they trust",
    "politics, parties and government",
    "the issues they care about most, and why",
    "hopes and worries for the next few years",
]


def _level(var: str, value: Any) -> str:
    return P.LEVEL_LABELS.get(value, str(value).replace("_", " "))


def describe_big5(big5: dict[str, float]) -> str:
    names = {
        "O": ("curious and open to new ideas", "conventional and set in their ways"),
        "C": ("organized and dependable", "disorganized and impulsive"),
        "E": ("outgoing and talkative", "reserved and private"),
        "A": ("warm and trusting", "blunt and suspicious"),
        "N": ("anxious and easily stressed", "calm and even-keeled"),
    }
    parts = []
    for k, (hi, lo) in names.items():
        v = big5.get(k, 0.5)
        if v >= 0.65:
            parts.append(hi)
        elif v <= 0.35:
            parts.append(lo)
    return ", ".join(parts) or "fairly middle-of-the-road temperament"


def full_card(demo: dict, traits: dict, geography: str = "") -> str:
    """Every known attribute, as used for persona generation and 'full' prompts."""
    lines = []
    if demo.get("age") is not None:
        lines.append(f"Age: {demo['age']}")
    elif demo.get("age_band"):
        lines.append(f"Age: {demo['age_band']}")
    for var in ("gender", "race", "education", "income", "urbanicity", "region"):
        if demo.get(var):
            lines.append(f"{P.LABELS[var]}: {_level(var, demo[var])}")
    if geography or demo.get("state"):
        lines.append(f"Lives in: {demo.get('state') or geography}")
    if demo.get("party"):
        lean = demo.get("lean")
        lean_txt = f" (leans {'Democratic' if lean == 'dem' else 'Republican'})" if demo["party"] == "independent" and lean in ("dem", "rep") else ""
        lines.append(f"Party identification: {demo['party']}{lean_txt}")
    if demo.get("ideology"):
        lines.append(f"Ideology: {demo['ideology']}")
    if demo.get("vote_2024"):
        vote = {"dem": "voted for the Democrat", "rep": "voted for the Republican", "other": "voted third party",
                "nonvoter": "did not vote"}[demo["vote_2024"]]
        lines.append(f"2024 presidential election: {vote}")
    if traits:
        lines.append(f"Occupation: {traits.get('occupation', '')}")
        lines.append(f"Household: {traits.get('household', '')}")
        lines.append(f"Religion: {traits.get('religion', '')}")
        lines.append(f"Temperament: {describe_big5(traits.get('big5', {}))}")
        lines.append(f"News sources: {', '.join(traits.get('news_diet', []))}")
        lines.append(f"Issues on their mind: {', '.join(traits.get('salient_issues', []))}")
        lines.append(f"Social media use: {traits.get('social_media_use', '')}")
    return "\n".join(lines)


def light_card(agent: dict, geography: str = "") -> str:
    """Name, age, gender, place, work, household: no party or ideology labels (they stereotype)."""
    demo, traits = agent.get("demographics", {}), agent.get("traits", {})
    bits = [agent.get("first_name") or "This person"]
    if demo.get("age") is not None:
        bits.append(str(demo["age"]))
    elif demo.get("age_band"):
        bits.append(f"age {demo['age_band']}")
    if demo.get("gender"):
        bits.append({"female": "woman", "male": "man"}.get(demo["gender"], demo["gender"]))
    line = ", ".join(bits)
    place = demo.get("state") or geography
    where = []
    if demo.get("urbanicity"):
        where.append(f"{demo['urbanicity']} area")
    if place:
        where.append(place)
    if where:
        line += f". Lives in a {' in '.join(where)}" if demo.get("urbanicity") else f". Lives in {place}"
    out = [line + "."]
    if traits.get("occupation"):
        out.append(f"Work: {traits['occupation']}. Household: {traits.get('household', 'n/a')}.")
    return "\n".join(out)


def persona_block(agent: dict, detail: str = "light", geography: str = "") -> str:
    """The cached per-agent context for panel and backtest calls."""
    demo, traits = agent.get("demographics", {}), agent.get("traits", {})
    has_record = bool(agent.get("transcript") or agent.get("raw"))
    card = light_card(agent, geography) if detail == "light" and has_record else (
        f"Name: {agent.get('first_name') or 'n/a'}\n" + full_card(demo, traits, geography)
    )
    parts = [f"<person>\n{card}"]
    if agent.get("identity"):
        parts.append(f"\nIn their own words: {agent['identity']}")
    parts.append("</person>")
    if agent.get("transcript"):
        parts.append(f"<interview>\n{agent['transcript']}\n</interview>")
    if agent.get("raw"):
        qa = "\n".join(f"Q: {k}\nA: {v}" for k, v in agent["raw"].items())
        parts.append(f"<survey_responses>\n{qa}\n</survey_responses>")
    refl = agent.get("reflections") or {}
    if any(refl.get(k) for k in EXPERT_LABELS):
        parts.append("<expert_observations>")
        for key, label in EXPERT_LABELS.items():
            notes = refl.get(key) or []
            if notes:
                parts.append(f"{label}:\n" + "\n".join(f"- {n}" for n in notes))
        parts.append("</expert_observations>")
    return "\n".join(parts)


def persona_task(agent: dict, words: int, per_expert: int, geography: str) -> str:
    topics = "\n".join(f"{i}. {t}" for i, t in enumerate(INTERVIEW_TOPICS, 1))
    return f"""<card>
{full_card(agent['demographics'], agent['traits'], geography)}
</card>

Write a transcript of about {words} words between an interviewer and this person, covering these topics in order \
(the interviewer asks one opening question per topic and a follow-up where the answer invites one):
{topics}

Then, as each of four experts who read the transcript (psychologist, behavioral economist, political scientist, \
demographer), give {per_expert} observations of at most 25 words each that would help predict this person's answers \
to new survey questions and reactions to news, ads and products.

Also give their first name and a 2-3 sentence first-person identity statement, the kind of thing they'd write in a \
social media bio."""


def reflections_task(per_expert: int, has_interview: bool) -> str:
    source = "interview" if has_interview else "survey responses"
    return f"""Read this person's {source} above. As each of four experts (psychologist, behavioral economist, political \
scientist, demographer), give {per_expert} observations of at most 25 words each that would help predict this person's \
answers to new survey questions and reactions to news, ads and products. Ground them in what the person actually said; \
mark anything that is an inference rather than stated with "(inferred)". Do not guess demographic facts that are missing.

Also give a plausible pseudonym first name (never a real name from the data) and a 2-3 sentence first-person identity \
statement in their voice."""


def routing_task(questions: list[dict]) -> str:
    rubric = "\n".join(f"- {k}: {v}" for k, v in P.EXPERT_RUBRIC.items())
    qs = "\n".join(f"- {q['id']}: {q['text']}" for q in questions)
    return f"""For each survey question below, pick the one expert whose observations about a respondent would best \
predict that respondent's answer.

Experts:
{rubric}

Questions:
{qs}"""


def _question_lines(questions: list[dict]) -> str:
    lines = []
    for i, q in enumerate(questions, 1):
        line = f"{i}. [q_{q['id']}] {q['text']}"
        if q["kind"] == "single_choice":
            line += "\n   Options: " + " | ".join(q["options"])
        elif q["kind"] == "scale":
            lo, hi = q.get("scale_labels") or ["", ""]
            line += f"\n   Answer with a whole number from {q['scale_min']} ({lo or 'lowest'}) to {q['scale_max']} ({hi or 'highest'})."
        else:
            line += "\n   Answer in your own words, at most 40 words."
        lines.append(line)
    return "\n".join(lines)


def stimulus_text(arm: dict, placebo_index: int = 0) -> str:
    if arm["kind"] == "control":
        if arm.get("control_mode") == "none":
            return "Nothing in particular caught your attention today; it was an ordinary day."
        return "Today you came across this:\n<stimulus>\n" + P.PLACEBOS[placebo_index % len(P.PLACEBOS)] + "\n</stimulus>"
    fmt = P.STIMULUS_FORMATS.get(arm.get("format") or "other", "this")
    src = f" ({arm['source']})" if arm.get("source") else ""
    return f"Today you came across {fmt}{src}:\n<stimulus>\n{arm['text'].strip()}\n</stimulus>"


def panel_task(
    first_name: str, context: str, arm: dict, questions: list[dict], routes: dict[str, str], placebo_index: int = 0
) -> str:
    experts = sorted({routes.get(q["id"]) or q.get("expert") or "political_scientist" for q in questions})
    hint = " and ".join(EXPERT_LABELS[e].lower() for e in experts)
    ctx = f"Background you know about:\n<context>\n{context.strip()}\n</context>\n\n" if context.strip() else ""
    return f"""{ctx}{stimulus_text(arm, placebo_index)}

Pay it the attention {first_name or 'this person'} realistically would. When answering, lean on what the {hint} \
noticed about you.

First write `reasoning`: 2-4 first-person sentences of what went through your mind. Then answer every question:
{_question_lines(questions)}"""


def summary_task(digest: str) -> str:
    return f"""Below are the results of a simulated message test: toplines per arm, paired effects of each treatment \
versus the control (the same simulated people answered under every arm), segment effects, and verbatim quotes.

{digest}

Write a focus-group style debrief. Rules:
- Treat these as simulated respondents; say so where it matters.
- Make segment claims only where the effect's interval excludes zero and n is at least 30; otherwise call it a hint.
- Quote respondents verbatim (copy the quote text exactly).
- Be candid about lines or arms that backfire, and why.
- Recommended edits must be concrete rewrites or cuts."""


# ---------------------------------------------------------------- social (POSIM)

SOCIAL_SYSTEM = """You are role-playing one account on a Twitter/Weibo-style microblog in a research simulation of how \
public opinion spreads. The <account> block describes who you are. Each time you are called, you have just opened the app.

Work through the Social-BDI loop, in order:
1. Perception: notice what is in your feed, what is trending, and any breaking news.
2. Belief update: update your opinions (subject, opinion, stance from -1 to +1, reason) and your emotions (happy, sad, \
angry, fear, surprise, disgust, each 0-1). Real people do not update like scientists. Ordinary users show confirmation \
bias (accept what fits their views, dismiss what doesn't), anchoring on first impressions, emotional contagion from what \
they read, herd mentality (following what seems popular), emotion-first reasoning when upset, and simplistic attribution \
(one villain, one cause). Opinion leaders and news outlets also weigh their reputation, professional judgment, which way \
the crowd is moving, and consistency with what they said before.
3. Desire: choose the motive that drives you right now and its intensity. Ordinary users: emotional venting, \
entertainment, self-expression, social approval, social connection, justice advocacy, information seeking. Opinion \
leaders: influencing others, self-expression, social approval, justice advocacy, information seeking. News outlets: \
inform audience, attract attention, information seeking.
4. Intention: choose 0-2 actions. Most of the time people scroll past; returning no actions is normal, especially if \
nothing in the feed touches you. Actions:
   - like: endorse a post or comment (no text)
   - repost: share a post as-is (no text)
   - repost_with_comment: share a post with your own text on top
   - short_comment / long_comment: reply to a post or comment (short is at most 280 characters, long at most 1,200)
   - short_post / long_post: write a new post of your own (target_id empty)
   For each action set the expression strategy (emotion, intensity, stance toward the focal subject, style, narrative) \
and then write the text in your own voice: typos, slang, all caps, emoji, sarcasm and bluntness are fine if they fit you. \
Use 0-3 topic hashtags.

Psychological types:
- curiosity_seeking: reads around, asks questions, updates on new facts.
- self_actualization: posts to express identity and values, wants to be heard.
- bandwagon: takes cues from what the crowd and people they follow seem to think.
- cathartic_venting: uses posting to blow off frustration; quick to anger.
- anti_authority: distrusts officials, institutions and media; assumes spin or cover-up.

Stay in character. Hostility is allowed but no slurs, no threats, no targeting private individuals. Never mention being \
an AI or a simulation. target_id must be an id shown in brackets in your feed (a post or a comment), or empty for a new post."""

ROLE_TEXT = {
    "ordinary": "an ordinary user",
    "opinion_leader": "a popular account with a large following (an opinion leader)",
    "media": "the social media account of a news outlet",
    "official": "an official account",
}


def social_persona_block(agent: dict | None, account: dict, geography: str = "") -> str:
    role = ROLE_TEXT.get(account["role"], "a user")
    if agent is None:
        slant = account.get("slant", 0.0)
        lean = "left-leaning" if slant < -0.3 else "right-leaning" if slant > 0.3 else "mainstream, center"
        return (f"<account>\nYou run @{account['name']}, {role}: a {lean} outlet. You post news updates, follow-ups and "
                f"headlines that get clicks; you rarely comment.\n</account>")
    traits = agent.get("traits", {})
    psych = traits.get("psych_type", "curiosity_seeking")
    parts = [f"<account>\n@{account['name']} is {role}.", light_card(agent, geography)]
    if agent.get("identity"):
        parts.append(f"Bio: {agent['identity']}")
    parts.append(f"Psychological type: {psych}. Uses social media: {traits.get('social_media_use', 'daily')}.")
    parts.append(f"News sources: {', '.join(traits.get('news_diet', []))}. Issues on their mind: "
                 f"{', '.join(traits.get('salient_issues', []))}.")
    if not agent.get("transcript") and not agent.get("raw"):
        parts.append(full_card(agent.get("demographics", {}), traits, geography))
    parts.append("</account>")
    if agent.get("transcript"):
        excerpt = agent["transcript"]
        idx = excerpt.lower().find("politic")
        start = max(0, idx - 600) if idx > 0 else 0
        parts.append("<interview_excerpt>\n" + excerpt[start: start + 2600] + "\n</interview_excerpt>")
    if agent.get("raw"):
        qa = list(agent["raw"].items())[:25]
        parts.append("<survey_excerpt>\n" + "\n".join(f"Q: {k}\nA: {v}" for k, v in qa) + "\n</survey_excerpt>")
    refl = agent.get("reflections") or {}
    notes = (refl.get("psychologist") or [])[:3] + (refl.get("political_scientist") or [])[:3]
    if notes:
        parts.append("<expert_notes>\n" + "\n".join(f"- {n}" for n in notes) + "\n</expert_notes>")
    return "\n".join(parts)
