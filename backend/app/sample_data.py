"""A fictional demo campaign with synthetic polls that contain known, planted event effects.

Nothing here describes a real person or race. The planted effects let you check that the
analytics recover what was put in (see tests/test_analytics.py).
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from .models import Candidate, Event, Poll

SEGMENTS = {
    # segment: (baseline support, share of sample)
    "Independents": (37.0, 0.30),
    "Women": (46.5, 0.52),
    "Under 35": (48.0, 0.20),
}

POLLSTERS = {
    # name: (house effect in pp, typical n, population)
    "Keystone Research": (1.4, 900, "LV"),
    "Harbor Polling": (-1.1, 700, "LV"),
    "Meridian Insights": (0.4, 1200, "RV"),
    "Lakeview University": (-0.5, 600, "RV"),
    "Civic Pulse Online": (1.8, 1500, "A"),
    "Northstar Strategies": (-1.3, 800, "LV"),
}

# effects: {segment: pp shift}; "All" is the topline. decay = share of the effect that fades over 45 days.
DEMO_EVENTS: list[dict] = [
    {
        "date": "2026-01-20",
        "type": "speech",
        "title": "Campaign launch speech in Riverton",
        "venue": "Riverton Union Hall",
        "audience": "Union members, local press",
        "topics": ["economy", "cost of living"],
        "tone": "optimistic",
        "summary": "Kickoff speech framing the race around grocery, rent and energy costs, with a promise of a state 'cost-of-living audit'.",
        "content": (
            "\"I'm running because a paycheck in this state doesn't stretch the way it did ten years ago. "
            "Rent is up 31 percent. Groceries are up. Your utility bill is up. Your wages? Not so much.\"\n"
            "\"On day one I will order a full cost-of-living audit of every fee this state charges families, "
            "and anything that can't justify itself goes.\"\n"
            "\"I'm not here to tell you everything is fine. I'm here to tell you it can be better, and here's how.\""
        ),
        "effects": {"All": 1.5, "Independents": 2.0, "Women": 1.5, "Under 35": 1.2},
        "decay": 0.2,
    },
    {
        "date": "2026-02-12",
        "type": "town_hall",
        "title": "Healthcare town hall in Bellmont",
        "venue": "Bellmont Community College",
        "audience": "Open public town hall, ~400 attendees",
        "topics": ["healthcare", "cost of living"],
        "tone": "empathetic",
        "summary": "Took unscreened questions for 90 minutes; personal story about a parent's medical debt; proposed capping insulin and ER facility fees.",
        "content": (
            "\"My mother spent the last two years of her life on the phone with billing departments. Nobody should spend "
            "their last good years fighting a collections agency.\"\n"
            "\"We will cap insulin at 35 dollars a month and ban surprise facility fees at emergency rooms. Full stop.\"\n"
            "Q: How will you pay for it? A: \"The fee ban costs the state nothing. The insulin cap is paid for by "
            "closing the pharmacy-benefit-manager rebate loophole, and I'll publish the numbers.\""
        ),
        "effects": {"All": 1.0, "Independents": 0.8, "Women": 1.8, "Under 35": 0.5},
        "decay": 0.3,
    },
    {
        "date": "2026-03-05",
        "type": "interview",
        "title": "Morning radio interview: 'I don't track gas prices'",
        "venue": "WKRT Morning Drive",
        "audience": "Commuter radio audience",
        "topics": ["economy", "cost of living", "character"],
        "tone": "dismissive",
        "summary": "Asked the price of a gallon of gas, said 'Honestly I don't really track that, my staff handles the car.' Clip went viral; opponent ran it in ads.",
        "content": (
            "Host: \"Quick one: what's a gallon of regular going for right now?\"\n"
            "\"Honestly, I don't really track that. My staff handles the car most days.\"\n"
            "Host: \"You've built your campaign on cost of living though.\"\n"
            "\"Sure, and the policy is what matters, not trivia.\""
        ),
        "effects": {"All": -3.0, "Independents": -4.0, "Women": -2.4, "Under 35": -1.6},
        "decay": 0.45,
    },
    {
        "date": "2026-03-28",
        "type": "ad",
        "title": "'Kitchen Table' TV and digital ad buy",
        "venue": "Statewide broadcast + streaming",
        "audience": "Persuadable voters 35-64",
        "topics": ["cost of living", "economy"],
        "tone": "warm",
        "summary": "60-second ad of the candidate at a family's kitchen table going through their monthly bills line by line.",
        "content": (
            "Narrator: \"Morgan Ellery sat down with the Ruiz family to go through their bills.\"\n"
            "Ellery: \"Your electric bill went up 22 dollars this year and 9 of it is a fee the state added. That's the "
            "first thing I'm cutting.\"\n"
            "Closing: \"Real costs. Real cuts. Morgan Ellery.\""
        ),
        "effects": {"All": 0.8, "Independents": 1.0, "Women": 1.0, "Under 35": 0.3},
        "decay": 0.3,
    },
    {
        "date": "2026-04-18",
        "type": "vote",
        "title": "Votes for the Regional Transit Modernization Act",
        "venue": "State Senate floor",
        "audience": "Legislative record",
        "topics": ["infrastructure", "transportation"],
        "tone": "neutral",
        "summary": "Voted yes on a bonding bill for regional rail and bus upgrades; low media coverage.",
        "content": "Floor remarks: \"This is boring and it matters. A bus that comes on time is a pay raise for the people who ride it.\"",
        "effects": {"All": 0.2, "Independents": 0.0, "Women": 0.2, "Under 35": 0.8},
        "decay": 0.0,
    },
    {
        "date": "2026-05-09",
        "type": "debate",
        "title": "Debate #1 (Channel 6): housing exchange",
        "venue": "Channel 6 studios",
        "audience": "Televised, ~600k viewers",
        "topics": ["housing", "cost of living"],
        "tone": "confident",
        "summary": "Strongest moment was a detailed answer on zoning reform and a starter-home tax credit; widely rated the winner in snap polls.",
        "content": (
            "\"My opponent says the market will fix housing. The market built 4,000 homes last year. We needed 19,000.\"\n"
            "\"We will legalize starter homes on lots zoned for one mansion, and give first-time buyers a 7,500 dollar "
            "credit, paid for by ending the out-of-state investor tax break.\"\n"
            "\"If you're 29 and living with your parents, this campaign is for you.\""
        ),
        "effects": {"All": 2.4, "Independents": 2.8, "Women": 1.6, "Under 35": 4.0},
        "decay": 0.25,
    },
    {
        "date": "2026-05-30",
        "type": "statement",
        "title": "Statement backing expanded immigration enforcement partnership",
        "venue": "Press release + press gaggle",
        "audience": "Statewide press",
        "topics": ["immigration", "public safety"],
        "tone": "hardline",
        "summary": "Endorsed expanding a state-federal enforcement partnership; seen as a reversal by part of the base and as inauthentic by independents.",
        "content": (
            "\"I support expanding the 287(g) partnership to every county that wants it.\"\n"
            "Reporter: \"Two years ago you called that program a mistake.\" \"Circumstances change and so do I.\""
        ),
        "effects": {"All": -1.8, "Independents": -3.8, "Women": -1.2, "Under 35": -2.6},
        "decay": 0.2,
    },
    {
        "date": "2026-06-20",
        "type": "endorsement",
        "title": "Endorsed by the State Teachers Federation",
        "venue": "Federation convention",
        "audience": "Teachers, education press",
        "topics": ["education"],
        "tone": "celebratory",
        "summary": "Expected endorsement; brief acceptance remarks on classroom funding.",
        "content": "\"Every kid in this state deserves a teacher who isn't working a second job to make rent.\"",
        "effects": {"All": 0.4, "Independents": 0.0, "Women": 0.8, "Under 35": 0.3},
        "decay": 0.3,
    },
    {
        "date": "2026-07-11",
        "type": "interview",
        "title": "Combative long-form podcast interview",
        "venue": "The Long Table podcast",
        "audience": "Podcast audience, younger and online",
        "topics": ["media", "character"],
        "tone": "combative",
        "summary": "Two-hour interview; repeatedly attacked the press as 'lazy' and refused to answer a question about a staffer's resignation.",
        "content": (
            "\"Half the reporters covering this race couldn't find the Capitol without a GPS. They're lazy.\"\n"
            "Host: \"What happened with your deputy campaign manager?\" \"Next question.\"\n"
            "\"I'm not going to pretend to like people who write fiction about me.\""
        ),
        "effects": {"All": -1.5, "Independents": -2.1, "Women": -2.0, "Under 35": 0.4},
        "decay": 0.3,
    },
    {
        "date": "2026-08-02",
        "type": "policy",
        "title": "Rolls out 'Homes Within Reach' housing plan",
        "venue": "Construction site in Eastgate",
        "audience": "Press, local builders, young families",
        "topics": ["housing", "cost of living"],
        "tone": "optimistic",
        "summary": "Detailed 40-page plan: 60,000 homes in 5 years, starter-home zoning, rent-to-own pilot; costed by an outside budget office.",
        "content": (
            "\"Sixty thousand homes in five years. Not a slogan; it's a 40-page plan, and the Budget Institute scored it.\"\n"
            "\"If you're a nurse, a mechanic, a teacher, you should be able to buy a home in the town you serve.\"\n"
            "\"Build here. Live here. Stay here.\""
        ),
        "effects": {"All": 2.0, "Independents": 2.0, "Women": 1.6, "Under 35": 3.8},
        "decay": 0.15,
    },
    {
        "date": "2026-08-25",
        "type": "debate",
        "title": "Debate #2 (Statewide Public Radio): crime exchange",
        "venue": "Statewide Public Radio",
        "audience": "Radio + livestream",
        "topics": ["public safety"],
        "tone": "defensive",
        "summary": "Spent most of the crime segment rebutting the opponent's ad instead of offering a plan; post-debate coverage called it a loss.",
        "content": (
            "\"That ad is a lie and everybody knows it's a lie.\"\n"
            "Moderator: \"What would you do about rising car thefts?\" \"Well, first, let's be clear the numbers in that ad "
            "are cherry-picked...\"\n"
            "\"I've always supported police, always.\""
        ),
        "effects": {"All": -1.0, "Independents": -1.6, "Women": -0.8, "Under 35": -0.5},
        "decay": 0.2,
    },
    {
        "date": "2026-09-15",
        "type": "speech",
        "title": "Childcare costs speech at a daycare co-op",
        "venue": "Little Oaks Co-op, Ferris",
        "audience": "Parents, childcare workers",
        "topics": ["childcare", "cost of living"],
        "tone": "empathetic",
        "summary": "Proposed capping childcare costs at 7% of income for families under 150k, with a pay floor for childcare workers.",
        "content": (
            "\"Childcare in this state costs more than in-state tuition. Think about that.\"\n"
            "\"No family earning under 150,000 dollars will pay more than 7 percent of their income for childcare.\"\n"
            "\"And the people caring for our kids will earn at least 20 dollars an hour.\""
        ),
        "effects": {"All": 1.4, "Independents": 1.0, "Women": 3.0, "Under 35": 1.8},
        "decay": 0.1,
    },
    {
        "date": "2026-09-29",
        "type": "social_post",
        "title": "Attack post mocking opponent's business record",
        "venue": "Social media",
        "audience": "Online",
        "topics": ["character", "economy"],
        "tone": "mocking",
        "summary": "Meme-style post mocking the opponent's failed restaurant chain; drew criticism as petty.",
        "content": "\"Can't run a sandwich shop, wants to run a state budget. 🥪📉\"",
        "effects": {"All": -0.4, "Independents": -0.8, "Women": -0.5, "Under 35": 0.1},
        "decay": 0.0,
    },
]


def _latent(t: date, segment: str, base: float, drift: dict[date, float]) -> float:
    level = base + drift.get(t, 0.0)
    for ev in DEMO_EVENTS:
        d = date.fromisoformat(ev["date"])
        age = (t - d).days
        if age <= 0:
            continue
        size = ev["effects"].get(segment, ev["effects"]["All"])
        ramp = min(1.0, age / 3.0)  # effects land over ~3 days
        fade = 1 - ev["decay"] * min(1.0, age / 45.0)
        level += size * ramp * fade
    return level


def build_demo() -> tuple[dict, list[dict], list[dict]]:
    rng = random.Random(20260108)
    cand = Candidate(
        name="Morgan Ellery (demo)",
        office="Governor",
        party="Independent",
        jurisdiction="Lakeshore State (fictional)",
        opponent_name="Dana Whitcomb (demo)",
        election_date=date(2026, 11, 3),
        bio=(
            "Fictional demo candidate. Two-term state senator and former small-business owner running an "
            "affordability-focused campaign against a well-funded two-term incumbent. All data is synthetic."
        ),
        is_demo=True,
    )

    start, end = date(2026, 1, 2), date(2026, 10, 5)
    # slow random-walk drift shared by everyone
    drift: dict[date, float] = {}
    level, t = 0.0, start
    while t <= end:
        level += rng.gauss(0, 0.04)
        level *= 0.995
        drift[t] = level
        t += timedelta(days=1)

    polls: list[Poll] = []
    t = start
    names = list(POLLSTERS)
    while t <= end:
        pollster = rng.choice(names)
        house, typical_n, pop = POLLSTERS[pollster]
        n = max(350, int(rng.gauss(typical_n, typical_n * 0.15)))
        cand_true = _latent(t, "All", 43.0, drift)
        undecided = max(4.0, 11.0 - 0.02 * (t - start).days)
        opp_true = 100 - undecided - cand_true
        sd = math.sqrt(cand_true * (100 - cand_true) / n)
        v = cand_true + house + rng.gauss(0, sd) + rng.gauss(0, 0.5)
        o = opp_true - 0.6 * house + rng.gauss(0, sd) + rng.gauss(0, 0.5)
        moe = round(1.96 * sd, 1)
        polls.append(
            Poll(
                candidate_id=cand.id, date=t, pollster=pollster, sample_size=n, population=pop,
                metric="vote_share", segment="All", value=round(v), opponent_value=round(o), margin_of_error=moe,
            )
        )
        if rng.random() < 0.75:  # crosstabs
            for seg, (seg_base, share) in SEGMENTS.items():
                sub_n = max(80, int(n * share))
                st = _latent(t, seg, seg_base, drift)
                ssd = math.sqrt(st * (100 - st) / sub_n)
                sv = st + house + rng.gauss(0, ssd) + rng.gauss(0, 1.0)
                seg_undecided = undecided * (2.2 if seg == "Independents" else 1.0)
                so = (100 - seg_undecided - st) - 0.6 * house + rng.gauss(0, ssd)
                polls.append(
                    Poll(
                        candidate_id=cand.id, date=t, pollster=pollster, sample_size=sub_n, population=pop,
                        metric="vote_share", segment=seg, value=round(sv), opponent_value=round(so),
                        margin_of_error=round(1.96 * ssd, 1),
                    )
                )
        if rng.random() < 0.2:  # favorability question
            fav_true = 40.0 + 0.9 * (cand_true - 43.0)
            fsd = math.sqrt(fav_true * (100 - fav_true) / n)
            polls.append(
                Poll(
                    candidate_id=cand.id, date=t, pollster=pollster, sample_size=n, population=pop,
                    metric="favorability", segment="All", value=round(fav_true + house * 0.5 + rng.gauss(0, fsd)),
                    margin_of_error=round(1.96 * fsd, 1),
                )
            )
        t += timedelta(days=rng.choice([1, 1, 2, 2, 3]))

    events = [
        Event(
            candidate_id=cand.id,
            **{k: v for k, v in ev.items() if k not in ("effects", "decay")},
        )
        for ev in DEMO_EVENTS
    ]
    return (
        cand.model_dump(mode="json"),
        [p.model_dump(mode="json") for p in polls],
        [e.model_dump(mode="json") for e in events],
    )
