"""Agents: the seeded trait layer, LLM persona generation, and CSV import of real respondents."""

from __future__ import annotations

import csv
import io
import logging
import math
import re
from typing import Any

from .. import llm
from ..config import get_settings
from ..models import new_id, utcnow
from . import presets as P
from . import prompts as SP
from .sampling import pick, rng_for
from .schemas import PersonaOutput, ReflectionsOutput

# ---------------------------------------------------------------- traits (no LLM)


def build_traits(demo: dict, seed: Any) -> dict:
    """Stable personality, work, media and activity traits, conditioned on demographics."""
    rng = rng_for("traits", seed)
    age = demo.get("age") or 45
    band = demo.get("age_band") or "45-64"
    clamp = lambda x: round(min(1.0, max(0.0, x)), 2)  # noqa: E731
    big5 = {
        "O": clamp(rng.gauss(0.5, 0.15)),
        "C": clamp(rng.gauss(0.5 + 0.003 * (age - 45), 0.15)),
        "E": clamp(rng.gauss(0.5, 0.15)),
        "A": clamp(rng.gauss(0.5 + 0.002 * (age - 45), 0.15)),
        "N": clamp(rng.gauss(0.5 - 0.003 * (age - 45), 0.15)),
    }

    edu = demo.get("education") or "some_college"
    if band in P.NOT_WORKING and rng.random() < (0.8 if age >= 67 else 0.35 if age <= 22 else 0.05):
        occupation = P.NOT_WORKING[band]
    elif rng.random() < 0.06:
        occupation = rng.choice(["unemployed, looking for work", "stay-at-home parent", "on disability", "gig worker"])
    else:
        occupation = rng.choice(P.OCCUPATIONS[edu])

    party = demo.get("party") or "independent"
    ideology = demo.get("ideology") or "moderate"
    news_pool = list(P.NEWS[ideology]) + (P.NEWS_YOUNG if band in ("18-29", "30-44") else [])
    news = []
    while len(news) < 2:
        pick_ = rng.choice(news_pool)
        if pick_ not in news:
            news.append(pick_)
    issues_pool = list(P.ISSUES[party])
    rng.shuffle(issues_pool)
    issues = issues_pool[:3]

    rel_weights = [0.25, 0.12, 0.20, 0.02, 0.01, 0.02, 0.22, 0.09, 0.05, 0.02]
    if party == "republican" or ideology == "conservative":
        rel_weights = [w * m for w, m in zip(rel_weights, [2.0, 1.0, 1.1, 0.6, 0.5, 1.5, 0.6, 0.4, 0.5, 1.0])]
    if party == "democrat" or ideology == "liberal":
        rel_weights = [w * m for w, m in zip(rel_weights, [0.4, 1.0, 1.0, 1.6, 1.5, 0.5, 1.4, 1.8, 1.2, 1.0])]
    if demo.get("race") == "black":
        rel_weights[8] *= 8
    if demo.get("region") == "south":
        rel_weights[0] *= 1.5
    religion = pick(P.RELIGIONS, rel_weights, rng.random())

    sm = pick(P.SOCIAL_MEDIA_LEVELS, P.SOCIAL_MEDIA_BY_AGE.get(band, P.SOCIAL_MEDIA_BY_AGE["45-64"]), rng.random())
    mu = {"never": -3.0, "rarely": -1.5, "weekly": -0.7, "daily": 0.0, "hourly": 0.8}[sm]
    activity = round(math.exp(rng.gauss(mu, 0.5)), 3)

    names, weights = zip(*P.PSYCH_TYPES.items())
    base = [w for w, _ in weights]
    mult = {
        "curiosity_seeking": 0.5 + big5["O"],
        "self_actualization": 0.5 + big5["E"],
        "bandwagon": (0.5 + big5["A"]) * (1.5 - big5["O"]),
        "cathartic_venting": 0.5 + big5["N"],
        "anti_authority": (1.5 - big5["A"]) * (1.3 if party == "independent" else 1.0),
    }
    psych = pick(list(names), [b * mult[n] for b, n in zip(base, names)], rng.random())

    emotion = {e: 0.05 for e in P.EMOTIONS}
    emotion["happy"] = clamp(0.2 + 0.2 * (big5["E"] - 0.5) - 0.2 * (big5["N"] - 0.5))
    emotion["angry"] = clamp(0.05 + 0.1 * (1 - big5["A"]))
    emotion["fear"] = clamp(0.05 + 0.1 * big5["N"])

    return {
        "big5": big5,
        "occupation": occupation,
        "household": rng.choice(P.HOUSEHOLDS.get(band, P.HOUSEHOLDS["45-64"])),
        "religion": religion,
        "news_diet": news,
        "salient_issues": issues,
        "social_media_use": sm,
        "psych_type": psych,
        "activity": activity,
        "baseline_emotion": emotion,
    }


def default_name(demo: dict, seed: Any) -> str:
    return rng_for("name", seed).choice(P.FIRST_NAMES.get(demo.get("gender") or "other", P.FIRST_NAMES["other"]))


def new_agent(population_id: str, index: int, demo: dict, weight: float, source: str, seed: Any, **extra: Any) -> dict:
    traits = build_traits(demo, (seed, index))
    return {
        "id": new_id(),
        "population_id": population_id,
        "index": index,
        "source": source,
        "external_id": "",
        "demographics": demo,
        "traits": traits,
        "raw": {},
        "base_weight": weight,
        "weight": weight,
        "weight_cal": None,
        "persona_status": "pending",
        "persona_error": "",
        "first_name": default_name(demo, (seed, index)),
        "identity": "",
        "transcript": "",
        "reflections": None,
        "usage": {},
        "created_at": utcnow(),
    } | extra


# ---------------------------------------------------------------- LLM generation

GEN_LOG = logging.DEBUG


def generate_persona(agent: dict, population: dict) -> tuple[dict, dict]:
    """Interview transcript + four-expert reflections for a synthetic agent. Returns (patch, usage)."""
    s = get_settings()
    words = population.get("transcript_words", 900)
    out, usage = llm.structured(
        SP.persona_task(agent, words, population.get("reflections_per_expert", 6), population.get("geography", "")),
        PersonaOutput,
        system=SP.PERSONA_SYSTEM,
        effort="low",
        thinking="off",
        model=s.sim_model,
        max_tokens=int(words * 2.2) + 3000,
        timeout=s.sim_call_timeout * 2,
        max_retries=1,
        log_level=GEN_LOG,
    )
    return {
        "first_name": out.first_name.strip()[:40] or agent["first_name"],
        "identity": out.identity.strip(),
        "transcript": out.transcript.strip(),
        "reflections": out.reflections.model_dump(),
        "persona_status": "ready",
        "persona_error": "",
    }, usage


def generate_reflections(agent: dict, population: dict) -> tuple[dict, dict]:
    """Expert reflections (and a pseudonym) for an imported respondent. Returns (patch, usage)."""
    s = get_settings()
    record = SP.persona_block({**agent, "reflections": None, "identity": ""}, "full", population.get("geography", ""))
    out, usage = llm.structured(
        SP.reflections_task(population.get("reflections_per_expert", 6), bool(agent.get("transcript"))),
        ReflectionsOutput,
        system=SP.PERSONA_SYSTEM,
        blocks=[llm.Block(record)],
        effort="low",
        thinking="off",
        model=s.sim_model,
        max_tokens=4000,
        timeout=s.sim_call_timeout,
        max_retries=1,
        log_level=GEN_LOG,
    )
    return {
        "first_name": out.first_name.strip()[:40] or agent["first_name"],
        "identity": out.identity.strip(),
        "reflections": out.reflections.model_dump(),
        "persona_status": "ready",
        "persona_error": "",
    }, usage


# ---------------------------------------------------------------- CSV import

PII = re.compile(
    r"(^|_|\b)(name|first.?name|last.?name|full.?name|e-?mail|phone|mobile|cell|address|street|zip|postal|"
    r"ip(_?address)?|dob|birth.?date|date.?of.?birth|ssn|social.?security|lat|latitude|lon|lng|longitude|"
    r"device.?id|user.?agent)($|_|\b)",
    re.I,
)
ALIASES = {
    "age": ["age", "age_years", "respondent_age", "age_group", "agegroup", "age_band", "age_cat", "agecat"],
    "gender": ["gender", "sex", "gender_identity"],
    "race": ["race", "ethnicity", "race_ethnicity", "raceeth", "race4", "race5"],
    "education": ["education", "educ", "edu", "educ4", "education_level", "highest_degree", "degree"],
    "income": ["income", "hh_income", "household_income", "faminc", "inc"],
    "region": ["region", "census_region"],
    "state": ["state", "inputstate", "state_name"],
    "urbanicity": ["urbanicity", "urban_rural", "urban", "community", "community_type", "area"],
    "party": ["party", "party_id", "partyid", "pid", "pid3", "party_identification"],
    "lean": ["lean", "party_lean", "pid_lean", "leaning"],
    "ideology": ["ideology", "ideo", "ideo5", "ideology5", "political_ideology"],
    "vote_2024": ["vote_2024", "vote2024", "presvote24", "pres_vote_2024", "vote_pres_2024"],
    "weight": ["weight", "wt", "weights", "wgt", "final_weight", "commonweight", "survey_weight"],
    "id": ["id", "respondent_id", "caseid", "case_id", "resp_id", "rid", "responseid", "response_id"],
    "interview": ["interview", "transcript", "interview_text", "life_story", "open_ended_story"],
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.strip().lower()).strip("_")


def humanize(h: str) -> str:
    return re.sub(r"[_\s]+", " ", h).strip().capitalize()


def map_columns(header: list[str]) -> dict[str, Any]:
    """Which CSV column feeds which field, which are dropped as PII, and which become survey answers."""
    mapping: dict[str, str] = {}
    pii: list[str] = []
    for col in header:
        key = _norm_header(col)
        field = next((f for f, names in ALIASES.items() if key in names), None)
        if field and field not in mapping:
            mapping[field] = col
            continue
        if PII.search(key):
            pii.append(col)
    used = set(mapping.values()) | set(pii)
    answers = [c for c in header if c not in used and c.strip()]
    return {"mapping": mapping, "pii_dropped": pii, "answer_columns": answers}


def _age_band(age: int) -> str:
    return "18-29" if age < 30 else "30-44" if age < 45 else "45-64" if age < 65 else "65+"


def _norm_value(field: str, raw: str) -> tuple[Any, bool]:
    """Map a free-text CSV value to a canonical level. Returns (value, recognized)."""
    v = (raw or "").strip()
    low = v.lower()
    if not v or low in ("na", "n/a", "nan", "none", "missing", "refused", "skipped", "-", "don't know", "dk"):
        return None, True
    if field == "age":
        m = re.match(r"^(\d{2})(?:\.\d+)?$", low)
        if m and 18 <= int(m.group(1)) <= 110:
            return int(m.group(1)), True
        m = re.match(r"^(\d{2})\s*[-–to]+\s*(\d{2})", low)
        if m:
            mid = (int(m.group(1)) + int(m.group(2))) // 2
            return _age_band(mid), True
        if re.match(r"^(65|6[5-9]|7\d)\s*\+|^65 and|^65 or", low):
            return "65+", True
        return None, False
    if field == "gender":
        if low in ("f", "female", "woman", "women", "2"):
            return "female", True
        if low in ("m", "male", "man", "men", "1"):
            return "male", True
        return "other", True
    if field == "race":
        for key, lvl in (("hispanic", "hispanic"), ("latin", "hispanic"), ("black", "black"), ("african", "black"),
                         ("asian", "asian"), ("white", "white")):
            if key in low:
                return lvl, True
        return "other", True
    if field == "education":
        if any(k in low for k in ("post", "master", "doctor", "phd", "professional", "graduate degree", "jd", "md")):
            return "postgrad", True
        if (any(k in low for k in ("bachelor", "4-year", "4 year", "four year", "college grad")) or re.search(r"\b(ba|bs)\b", low)) and "some" not in low:
            return "bachelors", True
        if any(k in low for k in ("some college", "associate", "2-year", "2 year", "trade", "vocational", "some_college")):
            return "some_college", True
        if any(k in low for k in ("high school", "hs", "ged", "less than", "no high", "grade", "hs_or_less")):
            return "hs_or_less", True
        return None, False
    if field == "income":
        nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", low.replace("k", "000"))]
        if not nums:
            return None, False
        x = nums[0] if len(nums) == 1 or "under" in low or "less" in low else sum(nums[:2]) / 2
        if x < 1000:
            x *= 1000
        if "under" in low or "less" in low:
            x -= 1
        return ("<30k" if x < 30000 else "30-60k" if x < 60000 else "60-100k" if x < 100000 else "100-150k" if x < 150000 else "150k+"), True
    if field == "region":
        for lvl in P.LEVELS["region"]:
            if lvl in low.replace(" ", ""):
                return lvl, True
        return None, False
    if field == "urbanicity":
        for key, lvl in (("suburb", "suburban"), ("rural", "rural"), ("small town", "rural"), ("urban", "urban"), ("city", "urban")):
            if key in low:
                return lvl, True
        return None, False
    if field == "party":
        if "lean" in low and ("dem" in low or "rep" in low):
            return "independent", True
        if "dem" in low:
            return "democrat", True
        if "rep" in low or "gop" in low:
            return "republican", True
        if any(k in low for k in ("ind", "other", "none", "no party", "unaffiliated", "something else")):
            return "independent", True
        return None, False
    if field == "lean":
        if "dem" in low:
            return "dem", True
        if "rep" in low:
            return "rep", True
        if any(k in low for k in ("neither", "none", "no lean", "independent")):
            return "none", True
        return None, False
    if field == "ideology":
        if "lib" in low or "progress" in low:
            return "liberal", True
        if "cons" in low:
            return "conservative", True
        if "mod" in low or "middle" in low:
            return "moderate", True
        return None, False
    if field == "vote_2024":
        if any(k in low for k in ("harris", "dem", "biden")):
            return "dem", True
        if any(k in low for k in ("trump", "rep")):
            return "rep", True
        if any(k in low for k in ("did not", "didn't", "not vote", "no vote", "nonvoter", "did_not")):
            return "nonvoter", True
        return "other", True
    return v, True


def parse_rows(csv_text: str, mode: str) -> dict[str, Any]:
    """Parse one chunk. Returns {columns, rows: [{demographics, raw, transcript, weight, external_id}], unknown}."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    header = reader.fieldnames or []
    cols = map_columns(header)
    mapping = cols["mapping"]
    if mode == "interview" and "interview" not in mapping:
        raise ValueError("Interview mode needs a column named interview, transcript or interview_text.")
    unknown: dict[str, dict[str, int]] = {}
    out = []
    for raw_row in reader:
        demo: dict[str, Any] = {}
        for field in ("age", "gender", "race", "education", "income", "region", "urbanicity", "party", "lean", "ideology", "vote_2024"):
            col = mapping.get(field)
            if not col:
                continue
            val, ok = _norm_value(field, raw_row.get(col) or "")
            if not ok:
                unknown.setdefault(field, {})
                key = (raw_row.get(col) or "")[:40]
                unknown[field][key] = unknown[field].get(key, 0) + 1
            if field == "age" and isinstance(val, int):
                demo["age"], demo["age_band"] = val, _age_band(val)
            elif field == "age" and val is not None:
                demo["age"], demo["age_band"] = None, val
            elif val is not None:
                demo[field] = val
        if "state" in mapping:
            demo["state"] = (raw_row.get(mapping["state"]) or "").strip()[:40]
        if demo.get("party") == "democrat":
            demo["lean"] = "dem"
        elif demo.get("party") == "republican":
            demo["lean"] = "rep"
        weight = 1.0
        if "weight" in mapping:
            try:
                weight = max(0.0, float(raw_row.get(mapping["weight"]) or 1.0))
            except ValueError:
                weight = 1.0
        transcript = (raw_row.get(mapping["interview"]) or "").strip() if "interview" in mapping else ""
        answers = {}
        if mode != "interview":
            for col in cols["answer_columns"][:150]:
                val = (raw_row.get(col) or "").strip()
                if val:
                    answers[humanize(col)] = val[:500]
            # demographic answers are also useful as survey context
            for field in ("age", "gender", "race", "education", "income", "party", "ideology", "vote_2024"):
                col = mapping.get(field)
                if col and (raw_row.get(col) or "").strip():
                    answers.setdefault(humanize(col), (raw_row.get(col) or "").strip()[:200])
        if not transcript and not answers and not demo:
            continue
        out.append({
            "demographics": demo,
            "raw": answers,
            "transcript": transcript[:60_000],
            "weight": weight,
            "external_id": (raw_row.get(mapping["id"]) or "").strip()[:60] if "id" in mapping else "",
        })
    return {"columns": cols, "rows": out, "unknown_values": unknown}
