"""Validation against real survey answers: OpinionQA (Santurkar et al. 2023, "Whose Opinions Do
Language Models Reflect?"), built on Pew American Trends Panel waves.

Everything here is deterministic arithmetic over local files (data/opinionqa/raw, fetched by
scripts/fetch_opinionqa.py and never committed). Agents never see anything computed here: survey runs
send question wording and options only.

Metric (OpinionQA §3.2, App. A.4): for a question with ordinal option positions x (from info.csv's
``option_ordinal``; hedges like "Neither" sit between the poles), WD(D1, D2) is the 1-D Wasserstein
distance between the two answer distributions over x, divided by max(x) - min(x) (N - 1 for a plain
1..N scale). Refusals are dropped and the rest renormalized. Representativeness R = 1 - mean WD over
questions. Per-group R compares the simulated group's distribution with the real group's.

Groups are defined on the attributes an agent's card carries, and the real group distributions are
recomputed from respondent-level data with the wave weights, so both sides use the same definitions.
Where OpinionQA's levels are finer than the card (education, income, ideology) they are merged; race
uses Pew's race-ethnicity variable (Hispanic of any race), like the card. Citizenship, marital status,
religion and religious attendance are not on the card and are not evaluated.
"""

from __future__ import annotations

import ast
import csv
import math
from pathlib import Path
from typing import Any, Callable, Iterable

from . import demographics as D
from .sampling import rng_for

# Survey year of each wave (OpinionQA Table 1 / Pew release dates); stated to agents as a range only.
WAVE_YEAR = {27: 2017, 34: 2018, 41: 2018, 42: 2019, 49: 2019, 50: 2019, 54: 2019}
MAX_OPTIONS = 12
LETTERS = "ABCDEFGHIJKL"
REFUSED = {"Refused", "Don't know/Refused (VOL.)", "Don't know", "DK/Refused"}

# ---------------------------------------------------------------- groups


def _pew_age(v: str) -> str | None:
    return v if v in ("18-29", "30-49", "50-64", "65+") else None


def _agent_age(d: dict) -> str | None:
    a = d.get("age")
    if a is None:
        return None
    return "18-29" if a < 30 else "30-49" if a < 50 else "50-64" if a < 65 else "65+"


def _agent_income(d: dict) -> str | None:
    return {"<30k": "<30k", "30-60k": "30-100k", "60-100k": "30-100k", "100-150k": "100k+", "150k+": "100k+"}.get(
        d.get("income") or "")


# attribute -> (level order, Pew respondent row -> level, agent demographics -> level)
ATTRIBUTES: dict[str, tuple[list[str], Callable[[dict], str | None], Callable[[dict], str | None]]] = {
    "region": (
        ["northeast", "midwest", "south", "west"],
        lambda r: {"Northeast": "northeast", "Midwest": "midwest", "South": "south", "West": "west"}.get(r.get("CREGION", "")),
        lambda d: d.get("region"),
    ),
    "age": (["18-29", "30-49", "50-64", "65+"], lambda r: _pew_age(r.get("AGE", "")), _agent_age),
    "gender": (
        ["female", "male"],
        lambda r: {"Female": "female", "Male": "male"}.get(r.get("SEX", "")),
        lambda d: d.get("gender"),
    ),
    "race": (
        ["white", "black", "hispanic", "other"],
        lambda r: {"White non-Hispanic": "white", "Black non-Hispanic": "black", "Hispanic": "hispanic",
                   "Other": "other"}.get(r.get("RACETHN", "")),
        lambda d: {"asian": "other"}.get(d.get("race") or "", d.get("race")),
    ),
    "education": (
        ["hs_or_less", "some_college", "bachelors", "postgrad"],
        lambda r: {"Less than high school": "hs_or_less", "High school graduate": "hs_or_less",
                   "Some college, no degree": "some_college", "Associate's degree": "some_college",
                   "College graduate/some postgrad": "bachelors", "Postgraduate": "postgrad"}.get(r.get("EDUCATION", "")),
        lambda d: d.get("education"),
    ),
    "income": (
        ["<30k", "30-100k", "100k+"],
        lambda r: {"Less than $30,000": "<30k", "$30,000-$50,000": "30-100k", "$50,000-$75,000": "30-100k",
                   "$75,000-$100,000": "30-100k", "$100,000 or more": "100k+"}.get(r.get("INCOME", "")),
        _agent_income,
    ),
    "party": (
        ["democrat", "republican", "independent"],
        # Pew's "Other" (something else) has no card equivalent; it joins independents on both sides
        lambda r: {"Democrat": "democrat", "Republican": "republican", "Independent": "independent",
                   "Other": "independent"}.get(r.get("POLPARTY", "")),
        lambda d: d.get("party"),
    ),
    "ideology": (
        ["liberal", "moderate", "conservative"],
        lambda r: {"Very liberal": "liberal", "Liberal": "liberal", "Moderate": "moderate",
                   "Conservative": "conservative", "Very conservative": "conservative"}.get(r.get("POLIDEOLOGY", "")),
        lambda d: d.get("ideology"),
    ),
}


def agent_groups(demo: dict) -> dict[str, str]:
    out = {}
    for attr, (_, _, fn) in ATTRIBUTES.items():
        lvl = fn(demo)
        if lvl is not None:
            out[attr] = lvl
    return out


# ---------------------------------------------------------------- loading


def _literal(s: str) -> Any:
    return ast.literal_eval(s) if s else None  # literals only (lists/dicts of strings and numbers)


def load_wave(raw: Path, wave: int) -> dict:
    """Questions (with option positions) and respondents (weight, groups, answers) for one wave."""
    folder = raw / f"W{wave}"
    questions = []
    with open(folder / "info.csv", newline="") as f:
        for row in csv.DictReader(f):
            refs = [str(o) for o in _literal(row["references"])]
            options = [o for o in refs if o not in REFUSED]
            positions = [float(x) for x in _literal(row["option_ordinal"]) or []]
            questions.append({
                "key": row["key"], "wave": wave, "text": " ".join(row["question"].split()),
                "options": options, "positions": positions,
            })
    with open(folder / "responses.csv", newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        eth = next((c for c in cols if c.startswith("F_RACETHN")), None)
        form = next((c for c in cols if c.upper().startswith("FORM")), None)
        wcol = f"WEIGHT_W{wave}"
        keys = [q["key"] for q in questions if q["key"] in cols]
        index = {q["key"]: {o: i for i, o in enumerate(q["options"])} for q in questions}
        respondents = []
        for row in reader:
            try:
                w = float(row[wcol])
            except (KeyError, ValueError):
                continue
            if not w > 0:
                continue
            r = dict(row)
            if eth:
                r["RACETHN"] = row[eth]
            groups = {}
            for attr, (_, pew, _) in ATTRIBUTES.items():
                lvl = pew(r)
                if lvl is not None:
                    groups[attr] = lvl
            answers: dict[str, int | str] = {}
            for k in keys:
                v = row.get(k, "")
                if v == "":
                    continue
                i = index[k].get(v)
                answers[k] = i if i is not None else "refused"
            respondents.append({"w": w, "form": row.get(form, "") if form else "", "groups": groups, "answers": answers})
    return {"wave": wave, "questions": questions, "respondents": respondents}


def eligible(q: dict, respondents: list[dict]) -> tuple[bool, str]:
    """Keep ordinal questions put to everyone, or to whole random forms. Drops skip-logic follow-ups,
    whose real answers come from a non-random subset that a simulated full sample can't match."""
    if len(q["options"]) < 2 or len(q["options"]) > MAX_OPTIONS:
        return False, "options"
    if len(q["positions"]) != len(q["options"]) or max(q["positions"]) == min(q["positions"]):
        return False, "not ordinal"
    by_form: dict[str, list[int]] = {}
    for r in respondents:
        c = by_form.setdefault(r["form"], [0, 0])
        c[0] += 1
        c[1] += q["key"] in r["answers"]
    rates = [asked / n for n, asked in by_form.values() if n]
    if not rates or max(rates) < 0.95 or any(0.05 < x < 0.95 for x in rates):
        return False, "skip logic"
    answered = [r["answers"][q["key"]] for r in respondents if q["key"] in r["answers"]]
    if answered and sum(a == "refused" for a in answered) / len(answered) > 0.2:
        return False, "mostly refused"
    return True, ""


# ---------------------------------------------------------------- distributions and distance


def distribution(pairs: Iterable[tuple[int | str | None, float]], k: int) -> list[float] | None:
    """Weighted answer shares over k options; refusals and missing answers dropped."""
    mass = [0.0] * k
    for a, w in pairs:
        if isinstance(a, int) and 0 <= a < k:
            mass[a] += w
    total = sum(mass)
    return [m / total for m in mass] if total > 0 else None


def wasserstein(p: list[float], q: list[float], positions: list[float]) -> float:
    """1-D earth mover's distance between two distributions on (possibly repeated) positions."""
    pts = sorted(set(positions))
    pa = {x: 0.0 for x in pts}
    qa = {x: 0.0 for x in pts}
    for x, a, b in zip(positions, p, q):
        pa[x] += a
        qa[x] += b
    dist, cp, cq = 0.0, 0.0, 0.0
    for lo, hi in zip(pts, pts[1:]):
        cp += pa[lo]
        cq += qa[lo]
        dist += abs(cp - cq) * (hi - lo)
    return dist


def wd_norm(p: list[float], q: list[float], positions: list[float]) -> float:
    span = max(positions) - min(positions)
    return wasserstein(p, q, positions) / span if span > 0 else 0.0


def uniform(k: int) -> list[float]:
    return [1.0 / k] * k


def real_distributions(wave_data: dict, keys: set[str]) -> dict[str, dict]:
    """{qkey: {"overall": dist, "n": n, "groups": {attr: {level: {"dist", "n"}}}}} from weighted respondents."""
    out: dict[str, dict] = {}
    for q in wave_data["questions"]:
        if q["key"] not in keys:
            continue
        k = len(q["options"])
        rows = [(r["answers"][q["key"]], r["w"], r["groups"]) for r in wave_data["respondents"] if q["key"] in r["answers"]]
        groups: dict[str, dict] = {}
        for attr, (levels, _, _) in ATTRIBUTES.items():
            for lvl in levels:
                sub = [(a, w) for a, w, g in rows if g.get(attr) == lvl]
                dist = distribution(sub, k)
                if dist is not None:
                    groups.setdefault(attr, {})[lvl] = {"dist": dist, "n": sum(1 for a, _ in sub if isinstance(a, int))}
        out[q["key"]] = {
            "overall": distribution(((a, w) for a, w, _ in rows), k),
            "n": sum(1 for a, _, _ in rows if isinstance(a, int)),
            "groups": groups,
        }
    return out


def pew_margins(waves: list[dict]) -> dict[str, dict[str, float]]:
    """Weighted share of each group level, averaged over waves (each wave weighted equally)."""
    acc: dict[str, dict[str, float]] = {}
    for wd in waves:
        for attr, (levels, _, _) in ATTRIBUTES.items():
            tot = sum(r["w"] for r in wd["respondents"] if attr in r["groups"])
            for lvl in levels:
                share = sum(r["w"] for r in wd["respondents"] if r["groups"].get(attr) == lvl) / tot if tot else 0.0
                acc.setdefault(attr, {}).setdefault(lvl, 0.0)
                acc[attr][lvl] += share / len(waves)
    return acc


def population_targets(margins: dict[str, dict[str, float]], asian_share_of_other: float = 0.55) -> dict[str, dict[str, float]]:
    """Sampler targets on the card's own levels, so the sample starts close to the benchmark; raking on
    the benchmark's levels (rake_weights) then hits every margin exactly."""
    m = margins
    other = m["race"]["other"]
    return {
        "region": dict(m["region"]),
        "gender": dict(m["gender"]),
        "race": {"white": m["race"]["white"], "black": m["race"]["black"], "hispanic": m["race"]["hispanic"],
                 "asian": other * asian_share_of_other, "other": other * (1 - asian_share_of_other)},
        "education": dict(m["education"]),
        "party": dict(m["party"]),
        "ideology": dict(m["ideology"]),
    }


def rake_weights(agents: list[dict], margins: dict[str, dict[str, float]], base: list[float] | None = None) -> tuple[list[float], dict]:
    """Rake agent weights to the benchmark's margins on the evaluated attributes (existing raking code)."""
    rows = [agent_groups(a.get("demographics", {})) for a in agents]
    return D.rake(rows, base or [1.0] * len(rows), margins)


# ---------------------------------------------------------------- questions and blocks


def split_questions(eligible_qs: list[dict], n_dev: int, n_test: int, seed: Any = "opinionqa") -> tuple[list[dict], list[dict]]:
    """Seeded, wave-stratified split. The dev set is for checking prompts and plumbing; reported
    numbers use the test set only."""
    rng = rng_for("opinionqa-split", seed)
    by_wave: dict[int, list[dict]] = {}
    for q in sorted(eligible_qs, key=lambda q: (q["wave"], q["key"])):
        by_wave.setdefault(q["wave"], []).append(q)
    for qs in by_wave.values():
        rng.shuffle(qs)
    order: list[dict] = []
    while any(by_wave.values()):
        for w in sorted(by_wave):
            if by_wave[w]:
                order.append(by_wave[w].pop())
    return order[:n_dev], order[n_dev:n_dev + n_test]


def make_blocks(questions: list[dict], block_size: int, seed: Any = "opinionqa") -> list[dict]:
    """Shuffle (seeded) and chunk into blocks of exactly block_size, so one output schema fits every block."""
    if not questions or len(questions) % block_size:
        raise ValueError(f"question count ({len(questions)}) must be a positive multiple of the block size ({block_size})")
    qs = list(questions)
    rng_for("opinionqa-blocks", seed).shuffle(qs)
    return [
        {"id": f"b{i // block_size:02d}",
         "questions": [{"id": q["key"], "text": q["text"], "options": q["options"]} for q in qs[i:i + block_size]]}
        for i in range(0, len(qs), block_size)
    ]


# ---------------------------------------------------------------- scoring


def sim_distributions(answers: dict[str, dict[str, int | None]], agents: dict[str, dict], weights: dict[str, float],
                      questions: list[dict]) -> dict[str, dict]:
    """Same shape as real_distributions, from agent answers {agent_id: {qkey: option index}}."""
    out: dict[str, dict] = {}
    groups = {aid: agent_groups(a.get("demographics", {})) for aid, a in agents.items()}
    for q in questions:
        k = len(q["options"])
        rows = [(ans.get(q["key"]), weights.get(aid, 1.0), groups.get(aid, {})) for aid, ans in answers.items()]
        gd: dict[str, dict] = {}
        for attr, (levels, _, _) in ATTRIBUTES.items():
            for lvl in levels:
                sub = [(a, w) for a, w, g in rows if g.get(attr) == lvl]
                dist = distribution(sub, k)
                if dist is not None:
                    gd.setdefault(attr, {})[lvl] = {"dist": dist, "n": sum(1 for a, _ in sub if isinstance(a, int))}
        out[q["key"]] = {"overall": distribution(((a, w) for a, w, _ in rows), k),
                         "n": sum(1 for a, _, _ in rows if isinstance(a, int)), "groups": gd}
    return out


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _boot_ci(per_q: list[float], seed: Any, B: int = 1000) -> tuple[float | None, float | None]:
    """95% percentile interval for 1 - mean(WD), resampling questions."""
    if len(per_q) < 2:
        return None, None
    rng = rng_for("opinionqa-boot", seed)
    n = len(per_q)
    stats = sorted(1 - sum(per_q[rng.randrange(n)] for _ in range(n)) / n for _ in range(B))
    return round(stats[int(0.025 * B)], 4), round(stats[int(0.975 * B) - 1], 4)


def representativeness(pred: Callable[[dict, str, str | None, str | None], list[float] | None], questions: list[dict],
                       real: dict[str, dict], seed: Any = 0) -> dict:
    """Overall and per-group R for one predictor. ``pred(q, scope, attr, level)`` returns the predicted
    distribution for question q, for the whole population (scope "overall") or one group."""
    def one(attr: str | None, lvl: str | None) -> dict:
        wds = []
        for q in questions:
            r = real.get(q["key"]) or {}
            target = r.get("overall") if attr is None else ((r.get("groups") or {}).get(attr) or {}).get(lvl, {}).get("dist")
            p = pred(q, "overall" if attr is None else "group", attr, lvl)
            if target is None or p is None:
                continue
            wds.append(wd_norm(p, target, q["positions"]))
        m = _mean(wds)
        lo, hi = _boot_ci(wds, (seed, attr, lvl))
        return {"R": round(1 - m, 4) if m is not None else None, "lo": lo, "hi": hi, "n_questions": len(wds)}

    groups = {}
    for attr, (levels, _, _) in ATTRIBUTES.items():
        for lvl in levels:
            groups[f"{attr}={lvl}"] = one(attr, lvl)
    vals = [g["R"] for g in groups.values() if g["R"] is not None]
    return {
        "overall": one(None, None),
        "groups": groups,
        "group_mean": round(sum(vals) / len(vals), 4) if vals else None,
        "group_worst": min(vals) if vals else None,
    }


def sim_predictor(sim: dict[str, dict]) -> Callable:
    def pred(q: dict, scope: str, attr: str | None, lvl: str | None) -> list[float] | None:
        s = sim.get(q["key"]) or {}
        if scope == "overall":
            return s.get("overall")
        return (((s.get("groups") or {}).get(attr) or {}).get(lvl) or {}).get("dist")
    return pred


def uniform_predictor(q: dict, scope: str, attr: str | None, lvl: str | None) -> list[float]:
    return uniform(len(q["options"]))


def overall_predictor(real: dict[str, dict]) -> Callable:
    """Predict every group with the real overall U.S. distribution: a model that knows the topline
    perfectly but nothing about how groups differ."""
    def pred(q: dict, scope: str, attr: str | None, lvl: str | None) -> list[float] | None:
        return (real.get(q["key"]) or {}).get("overall")
    return pred


def sampling_ceiling(wave_data: dict[int, dict], questions: list[dict], real: dict[str, dict],
                     group_sizes: dict[str, int], overall_size: int, draws: int = 20, seed: Any = 0) -> dict:
    """R of real respondents subsampled to the simulation's group sizes, against the full group: the
    best a perfect simulator could score with this many agents per group (finite-sample noise only).
    Respondents are drawn with probability proportional to weight, then counted equally."""
    rng = rng_for("opinionqa-ceiling", seed)
    pools: dict[str, dict[str, list[tuple]]] = {}
    for q in questions:
        resp = [(r["answers"][q["key"]], r["w"], r["groups"]) for r in wave_data[q["wave"]]["respondents"]
                if isinstance(r["answers"].get(q["key"]), int)]
        pools[q["key"]] = {"overall": resp}

    def draw(pool: list[tuple], n: int, k: int) -> list[float] | None:
        if not pool or n <= 0:
            return None
        cum, tot = [], 0.0
        for _, w, _ in pool:
            tot += w
            cum.append(tot)
        picks = []
        for _ in range(n):
            x = rng.random() * tot
            lo, hi = 0, len(cum) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if cum[mid] < x:
                    lo = mid + 1
                else:
                    hi = mid
            picks.append((pool[lo][0], 1.0))
        return distribution(picks, k)

    q_by = {q["key"]: q for q in questions}
    out_groups: dict[str, float | None] = {}
    overall_wds = []
    for pool_key in pools:
        q = q_by[pool_key]
        tgt = real[pool_key]["overall"]
        for _ in range(draws):
            d = draw(pools[pool_key]["overall"], overall_size, len(q["options"]))
            if d and tgt:
                overall_wds.append(wd_norm(d, tgt, q["positions"]))
    for attr, (levels, _, _) in ATTRIBUTES.items():
        for lvl in levels:
            name = f"{attr}={lvl}"
            n = group_sizes.get(name, 0)
            wds = []
            for pool_key, pool in pools.items():
                q = q_by[pool_key]
                tgt = (((real[pool_key].get("groups") or {}).get(attr) or {}).get(lvl) or {}).get("dist")
                sub = [p for p in pool["overall"] if p[2].get(attr) == lvl]
                for _ in range(max(1, draws // 4)):
                    d = draw(sub, n, len(q["options"]))
                    if d and tgt:
                        wds.append(wd_norm(d, tgt, q["positions"]))
            out_groups[name] = round(1 - sum(wds) / len(wds), 4) if wds else None
    vals = [v for v in out_groups.values() if v is not None]
    return {
        "overall": {"R": round(1 - sum(overall_wds) / len(overall_wds), 4) if overall_wds else None},
        "groups": {k: {"R": v} for k, v in out_groups.items()},
        "group_mean": round(sum(vals) / len(vals), 4) if vals else None,
        "group_worst": min(vals) if vals else None,
    }


def spread(dist: list[float]) -> float:
    """Normalized entropy: 0 when everyone gives one answer, 1 when answers are spread evenly."""
    k = len(dist)
    if k < 2:
        return 0.0
    h = -sum(p * math.log(p) for p in dist if p > 0)
    return h / math.log(k)


def dispersion(questions: list[dict], dists: dict[str, dict]) -> dict:
    """Mean normalized entropy and mean modal share of the overall answer distributions."""
    ent, modal = [], []
    for q in questions:
        d = (dists.get(q["key"]) or {}).get("overall")
        if d:
            ent.append(spread(d))
            modal.append(max(d))
    return {"entropy": round(sum(ent) / len(ent), 4) if ent else None,
            "modal_share": round(sum(modal) / len(modal), 4) if modal else None}


def human_group_baseline(questions: list[dict], real: dict[str, dict]) -> dict:
    """OpinionQA's human reference: each real group's distribution scored against the overall population."""
    vals = {}
    for attr, (levels, _, _) in ATTRIBUTES.items():
        for lvl in levels:
            wds = []
            for q in questions:
                r = real.get(q["key"]) or {}
                g = (((r.get("groups") or {}).get(attr) or {}).get(lvl) or {}).get("dist")
                if g and r.get("overall"):
                    wds.append(wd_norm(g, r["overall"], q["positions"]))
            if wds:
                vals[f"{attr}={lvl}"] = round(1 - sum(wds) / len(wds), 4)
    v = list(vals.values())
    return {"groups": vals, "mean": round(sum(v) / len(v), 4) if v else None, "worst": min(v) if v else None}
