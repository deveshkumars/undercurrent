"""Static tables: demographic presets and conditionals, trait vocabularies, questionnaires, placebo texts.

The demographic numbers are rounded approximations of recent Census/Pew/AP VoteCast figures for the
U.S.; they are a reasonable default, not an authoritative frame. Users override any margin with
targets (e.g. a district's partisan mix), and raking makes the weighted sample hit those targets.
"""

from __future__ import annotations

LEVELS: dict[str, list[str]] = {
    "age_band": ["18-29", "30-44", "45-64", "65+"],
    "gender": ["female", "male"],
    "race": ["white", "black", "hispanic", "asian", "other"],
    "region": ["northeast", "midwest", "south", "west"],
    "education": ["hs_or_less", "some_college", "bachelors", "postgrad"],
    "income": ["<30k", "30-60k", "60-100k", "100-150k", "150k+"],
    "urbanicity": ["urban", "suburban", "rural"],
    "party": ["democrat", "republican", "independent"],
    "lean": ["dem", "rep", "none"],
    "ideology": ["liberal", "moderate", "conservative"],
    "vote_2024": ["dem", "rep", "other", "nonvoter"],
}

LABELS: dict[str, str] = {
    "age_band": "Age",
    "gender": "Gender",
    "race": "Race / ethnicity",
    "region": "Region",
    "education": "Education",
    "income": "Household income",
    "urbanicity": "Community",
    "party": "Party ID",
    "lean": "Partisan lean",
    "ideology": "Ideology",
    "vote_2024": "2024 vote",
}

LEVEL_LABELS: dict[str, str] = {
    "hs_or_less": "HS or less",
    "some_college": "Some college",
    "bachelors": "Bachelor's",
    "postgrad": "Postgrad",
    "dem": "Dem",
    "rep": "Rep",
    "none": "None",
    "nonvoter": "Didn't vote",
}

ROOT_VARS = ("age_band", "gender", "race", "region")
# Sampled in this order; each depends only on earlier variables.
CHILD_VARS = ("education", "income", "urbanicity", "party", "lean", "ideology", "vote_2024")
TARGETABLE = ROOT_VARS + ("education", "income", "urbanicity", "party", "ideology", "vote_2024")

PRESETS: dict[str, dict] = {
    "us_adults": {
        "label": "U.S. adults",
        "description": "All adults 18+.",
        "margins": {
            "age_band": {"18-29": 0.20, "30-44": 0.26, "45-64": 0.32, "65+": 0.22},
            "gender": {"female": 0.51, "male": 0.49},
            "race": {"white": 0.60, "black": 0.12, "hispanic": 0.17, "asian": 0.06, "other": 0.05},
            "region": {"northeast": 0.17, "midwest": 0.21, "south": 0.38, "west": 0.24},
            "education": {"hs_or_less": 0.38, "some_college": 0.27, "bachelors": 0.22, "postgrad": 0.13},
            "party": {"democrat": 0.29, "republican": 0.28, "independent": 0.43},
            "vote_2024": {"dem": 0.30, "rep": 0.31, "other": 0.02, "nonvoter": 0.37},
        },
    },
    "us_registered_voters": {
        "label": "U.S. registered voters",
        "description": "Adults registered to vote.",
        "margins": {
            "age_band": {"18-29": 0.17, "30-44": 0.25, "45-64": 0.33, "65+": 0.25},
            "gender": {"female": 0.52, "male": 0.48},
            "race": {"white": 0.67, "black": 0.12, "hispanic": 0.12, "asian": 0.05, "other": 0.04},
            "region": {"northeast": 0.17, "midwest": 0.21, "south": 0.38, "west": 0.24},
            "education": {"hs_or_less": 0.33, "some_college": 0.29, "bachelors": 0.24, "postgrad": 0.14},
            "party": {"democrat": 0.33, "republican": 0.31, "independent": 0.36},
            "vote_2024": {"dem": 0.41, "rep": 0.42, "other": 0.02, "nonvoter": 0.15},
        },
    },
    "us_likely_voters": {
        "label": "U.S. likely voters",
        "description": "Registered voters likely to turn out in a general election.",
        "margins": {
            "age_band": {"18-29": 0.13, "30-44": 0.23, "45-64": 0.36, "65+": 0.28},
            "gender": {"female": 0.53, "male": 0.47},
            "race": {"white": 0.70, "black": 0.11, "hispanic": 0.11, "asian": 0.04, "other": 0.04},
            "region": {"northeast": 0.17, "midwest": 0.22, "south": 0.37, "west": 0.24},
            "education": {"hs_or_less": 0.28, "some_college": 0.29, "bachelors": 0.26, "postgrad": 0.17},
            "party": {"democrat": 0.35, "republican": 0.34, "independent": 0.31},
            "vote_2024": {"dem": 0.46, "rep": 0.47, "other": 0.02, "nonvoter": 0.05},
        },
    },
}

# P(child | parents). Keys of the outer dict are the parent level (tuple for several parents).
EDUCATION_BY_AGE = {
    "18-29": [0.38, 0.36, 0.21, 0.05],
    "30-44": [0.33, 0.26, 0.25, 0.16],
    "45-64": [0.38, 0.27, 0.21, 0.14],
    "65+": [0.42, 0.25, 0.18, 0.15],
}
INCOME_BY_EDUCATION = {
    "hs_or_less": [0.33, 0.29, 0.22, 0.10, 0.06],
    "some_college": [0.24, 0.27, 0.26, 0.14, 0.09],
    "bachelors": [0.12, 0.18, 0.26, 0.21, 0.23],
    "postgrad": [0.08, 0.13, 0.22, 0.22, 0.35],
}
URBANICITY_BY_REGION = {
    "northeast": [0.35, 0.50, 0.15],
    "midwest": [0.25, 0.45, 0.30],
    "south": [0.22, 0.48, 0.30],
    "west": [0.38, 0.47, 0.15],
}
PARTY_BY_RACE = {
    "white": [0.26, 0.38, 0.36],
    "black": [0.62, 0.06, 0.32],
    "hispanic": [0.38, 0.20, 0.42],
    "asian": [0.38, 0.17, 0.45],
    "other": [0.28, 0.25, 0.47],
}
# multipliers on [democrat, republican, independent]
PARTY_AGE_MULT = {
    "18-29": [1.0, 0.75, 1.3],
    "30-44": [1.0, 0.9, 1.1],
    "45-64": [1.0, 1.08, 0.95],
    "65+": [1.05, 1.15, 0.8],
}
PARTY_EDU_MULT = {
    "hs_or_less": [0.92, 1.12, 1.0],
    "some_college": [0.97, 1.05, 1.0],
    "bachelors": [1.1, 0.92, 1.0],
    "postgrad": [1.3, 0.8, 0.95],
}
PARTY_URBAN_MULT = {"urban": [1.25, 0.75, 1.0], "suburban": [1.0, 1.0, 1.0], "rural": [0.75, 1.3, 1.0]}
LEAN_BY_PARTY = {"democrat": [1.0, 0.0, 0.0], "republican": [0.0, 1.0, 0.0], "independent": [0.40, 0.38, 0.22]}
IDEOLOGY_BY_PARTY_LEAN = {
    ("democrat", "dem"): [0.52, 0.38, 0.10],
    ("republican", "rep"): [0.04, 0.24, 0.72],
    ("independent", "dem"): [0.32, 0.53, 0.15],
    ("independent", "rep"): [0.06, 0.40, 0.54],
    ("independent", "none"): [0.12, 0.60, 0.28],
}
VOTE_BY_LEAN = {
    "dem": [0.86, 0.05, 0.02, 0.07],
    "rep": [0.04, 0.88, 0.02, 0.06],
    "none": [0.25, 0.30, 0.07, 0.38],
}

FIRST_NAMES = {
    "female": [
        "Maria", "Linda", "Jasmine", "Karen", "Ashley", "Rosa", "Megan", "Tanya", "Grace", "Denise", "Priya",
        "Lauren", "Brenda", "Keisha", "Emily", "Sofia", "Carol", "Hannah", "Mei", "Debra", "Alicia", "Paula",
    ],
    "male": [
        "James", "Carlos", "Derek", "Michael", "Tyrone", "Kevin", "Luis", "Brian", "Ray", "Anthony", "Wei",
        "Gary", "Marcus", "Jose", "Daniel", "Travis", "Ahmed", "Steve", "Darnell", "Ethan", "Victor", "Doug",
    ],
    "other": ["Alex", "Jordan", "Sam", "Riley", "Casey", "Taylor"],
}

OCCUPATIONS = {
    "hs_or_less": [
        "warehouse associate", "home health aide", "truck driver", "cashier", "line cook", "construction laborer",
        "auto mechanic", "janitor", "machine operator", "retail stock clerk", "landscaper", "delivery driver",
    ],
    "some_college": [
        "medical assistant", "electrician", "office administrator", "police officer", "dental hygienist",
        "customer service rep", "HVAC technician", "insurance claims processor", "daycare worker", "bank teller",
        "IT help desk technician", "real estate agent",
    ],
    "bachelors": [
        "accountant", "elementary school teacher", "software developer", "registered nurse", "marketing manager",
        "sales representative", "civil engineer", "social worker", "small business owner", "HR specialist",
        "project manager", "financial analyst",
    ],
    "postgrad": [
        "attorney", "physician", "university lecturer", "pharmacist", "school principal", "research scientist",
        "therapist", "nonprofit director", "physical therapist", "management consultant", "architect", "librarian",
    ],
}
NOT_WORKING = {"18-29": "student", "65+": "retired"}

HOUSEHOLDS = {
    "18-29": ["lives with roommates", "lives with parents", "single, lives alone", "married, no kids yet",
              "single parent of a toddler", "lives with partner"],
    "30-44": ["married with two kids", "single parent of one", "married, no kids", "divorced, shares custody",
              "lives with partner and a baby", "single, lives alone"],
    "45-64": ["married, kids in high school", "empty nester", "divorced, lives alone", "cares for an aging parent",
              "married, adult kid moved back home", "remarried, blended family"],
    "65+": ["widowed, lives alone", "married, grandkids nearby", "lives with adult daughter", "married, on a fixed income",
            "divorced, lives alone", "in a retirement community"],
}

RELIGIONS = ["evangelical Protestant", "mainline Protestant", "Catholic", "Jewish", "Muslim", "Latter-day Saint",
             "nothing in particular", "atheist or agnostic", "Black Protestant", "Orthodox Christian"]

NEWS = {
    "liberal": ["NPR", "MSNBC", "The New York Times", "CNN", "late-night comedy clips", "Instagram news accounts",
                "The Washington Post", "podcasts"],
    "moderate": ["local TV news", "ABC/NBC/CBS evening news", "Facebook", "YouTube", "the local paper", "CNN",
                 "whatever comes up on their phone", "talk with coworkers"],
    "conservative": ["Fox News", "talk radio", "Facebook", "Newsmax", "The Wall Street Journal", "local TV news",
                     "YouTube commentators", "church friends"],
}
NEWS_YOUNG = ["TikTok", "YouTube", "Reddit", "podcasts", "Instagram", "X/Twitter"]

ISSUES = {
    "democrat": ["health care costs", "climate change", "abortion rights", "gun violence", "protecting democracy",
                 "cost of living", "public schools", "housing costs"],
    "republican": ["inflation", "immigration", "crime", "taxes", "gas prices", "government spending",
                   "border security", "cost of living"],
    "independent": ["cost of living", "housing costs", "health care costs", "jobs and wages", "corruption in government",
                    "public schools", "taxes", "crime"],
}

SOCIAL_MEDIA_BY_AGE = {
    # never, rarely, weekly, daily, hourly
    "18-29": [0.02, 0.05, 0.13, 0.45, 0.35],
    "30-44": [0.05, 0.08, 0.17, 0.48, 0.22],
    "45-64": [0.12, 0.13, 0.22, 0.43, 0.10],
    "65+": [0.25, 0.20, 0.23, 0.29, 0.03],
}
SOCIAL_MEDIA_LEVELS = ["never", "rarely", "weekly", "daily", "hourly"]

PSYCH_TYPES = {
    # POSIM's stable psychological types, with base rates
    "curiosity_seeking": (0.30, "Curious and information-seeking: reads around, asks questions, updates on new facts."),
    "self_actualization": (0.20, "Self-expressive: posts to articulate their identity and values, wants to be heard."),
    "bandwagon": (0.25, "Conformist: takes cues from what people around them and the crowd seem to think."),
    "cathartic_venting": (0.15, "Venter: uses talk and posts to blow off frustration; emotional, quick to anger."),
    "anti_authority": (0.10, "Anti-authority: distrusts officials, institutions and media; assumes spin or cover-up."),
}

EMOTIONS = ("happy", "sad", "angry", "fear", "surprise", "disgust")

PLACEBOS = [
    "Local news brief: The county transportation department says resurfacing on Route 9 between Oak Street and the "
    "fairgrounds will start Monday and last about three weeks. Expect lane closures from 9 a.m. to 3 p.m. on weekdays. "
    "Officials suggest using Mill Road as a detour.",
    "Weather: A mild, mostly dry week is ahead, with highs in the upper 60s and a chance of light showers on Thursday. "
    "Forecasters say the weekend should be clear for the regional farmers market and the high school homecoming game.",
    "Community news: The public library is extending weekend hours through the winter and adding a Saturday morning "
    "story time. The library will also host a free tax-preparation clinic in February; sign-ups open next month.",
]

STIMULUS_FORMATS = {
    "news_article": "a news article",
    "ad_script": "a political ad (script / description of what was shown)",
    "speech_excerpt": "an excerpt from a speech",
    "social_post": "a social media post",
    "debate_clip": "a clip from a debate",
    "policy_summary": "a summary of a policy proposal",
    "product_description": "a product announcement",
    "email": "an email",
    "other": "this",
}

# Each built-in question is routed to the expert whose reflections are most relevant to it.
EXPERT_RUBRIC = {
    "psychologist": "personality, emotions, relationships, stress, how they react in the moment",
    "behavioral_economist": "money, risk, effort, purchases, habits, sharing, turnout and other costly actions",
    "political_scientist": "parties, candidates, voting, policy positions, government and trust in institutions",
    "demographer": "life stage, place, work, family, group circumstances",
}


def _q(qid: str, text: str, kind: str, expert: str, **kw) -> dict:
    return {"id": qid, "text": text, "kind": kind, "expert": expert, "builtin": True, **kw}


def questionnaire(preset: str, subject: str, opponent: str = "") -> list[dict]:
    """Built-in question sets. ``subject`` is the candidate, product or policy being evaluated."""
    subject = subject.strip() or "the subject"
    if preset == "political":
        other = opponent.strip() or "the opponent"
        return [
            _q("thermometer", f"On a 0-100 feeling thermometer, how warm or cold do you feel toward {subject}? "
               "(0 = very cold, 50 = neutral, 100 = very warm)", "scale", "political_scientist",
               scale_min=0, scale_max=100, scale_labels=["very cold", "very warm"], primary=True),
            _q("vote_choice", f"If the election were held today, who would you vote for?", "single_choice",
               "political_scientist", options=[subject, other, "someone else", "undecided", "wouldn't vote"]),
            _q("turnout", "How likely are you to vote in this election, from 0 (certainly not) to 10 (certainly)?",
               "scale", "behavioral_economist", scale_min=0, scale_max=10, scale_labels=["certainly not", "certainly"]),
            _q("persuasion", f"Did anything you saw or heard today make you more or less likely to support {subject}?",
               "single_choice", "political_scientist", ordinal=True,
               options=["much more likely", "somewhat more likely", "no difference", "somewhat less likely", "much less likely"]),
            _q("emotion", "Which word best describes how you feel right now?", "single_choice", "psychologist",
               options=["hopeful", "proud", "reassured", "indifferent", "annoyed", "angry", "anxious", "disgusted"]),
            _q("emotion_intensity", "How strongly do you feel that, from 0 (barely) to 10 (very strongly)?", "scale",
               "psychologist", scale_min=0, scale_max=10, scale_labels=["barely", "very strongly"]),
            _q("would_share", "Would you share or bring up what you saw today with anyone?", "single_choice",
               "behavioral_economist", options=["yes, publicly online", "yes, privately with people I know", "no"]),
            _q("gut_reaction", "In a sentence or two, what was your honest gut reaction to what you saw today?", "open",
               "psychologist"),
            _q("tell_a_friend", f"What would you say about {subject} to a friend tonight?", "open", "political_scientist"),
        ]
    if preset == "product":
        return [
            _q("purchase_intent", f"How likely are you to buy or try {subject}?", "single_choice", "behavioral_economist",
               ordinal=True, primary=True,
               options=["definitely would", "probably would", "might or might not", "probably would not", "definitely would not"]),
            _q("appeal", f"How appealing is {subject} to you, from 0 (not at all) to 10 (extremely)?", "scale",
               "psychologist", scale_min=0, scale_max=10, scale_labels=["not at all", "extremely"]),
            _q("recommend", f"How likely are you to recommend {subject} to a friend, from 0 to 10?", "scale",
               "behavioral_economist", scale_min=0, scale_max=10, scale_labels=["not at all likely", "extremely likely"]),
            _q("price_fairness", "Does the price (if you know it) seem fair to you?", "single_choice", "behavioral_economist",
               options=["a great deal", "fair", "a bit expensive", "a rip-off", "no idea what it costs"]),
            _q("emotion", "Which word best describes how you feel about it?", "single_choice", "psychologist",
               options=["excited", "curious", "indifferent", "skeptical", "annoyed"]),
            _q("gut_reaction", "In a sentence or two, what was your honest gut reaction?", "open", "psychologist"),
            _q("tell_a_friend", f"What would you tell a friend about {subject}?", "open", "behavioral_economist"),
        ]
    if preset == "policy":
        return [
            _q("support", f"Do you support or oppose {subject}?", "single_choice", "political_scientist", ordinal=True,
               primary=True,
               options=["strongly support", "somewhat support", "neither", "somewhat oppose", "strongly oppose"]),
            _q("importance", "How important is this issue to you personally, from 0 (not at all) to 10 (extremely)?",
               "scale", "demographer", scale_min=0, scale_max=10, scale_labels=["not at all", "extremely"]),
            _q("personal_effect", "How would this affect you and your family?", "single_choice", "behavioral_economist",
               options=["help us a lot", "help us a little", "no real effect", "hurt us a little", "hurt us a lot"],
               ordinal=True),
            _q("trust", "How much do you trust the people behind it to carry it out well, from 0 to 10?", "scale",
               "political_scientist", scale_min=0, scale_max=10, scale_labels=["not at all", "completely"]),
            _q("emotion", "Which word best describes how you feel about it?", "single_choice", "psychologist",
               options=["hopeful", "relieved", "indifferent", "worried", "angry"]),
            _q("gut_reaction", "In a sentence or two, what was your honest gut reaction?", "open", "psychologist"),
            _q("tell_a_friend", "What would you tell a friend about it?", "open", "political_scientist"),
        ]
    return []
