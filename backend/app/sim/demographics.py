"""Stratified synthetic samples and survey weights.

1. Root variables (age, gender, race, region) get exact counts by largest remainder.
2. Child variables are drawn from conditional tables. Per-level "tilt" factors are fitted on a large
   pre-sample (with common random numbers, so the fit is smooth) until the implied margins match the
   targets: a Monte-Carlo version of iterative proportional fitting on the conditionals.
3. Raking adjusts weights so every target margin is hit exactly; weights are trimmed to [w/5, 5w].
"""

from __future__ import annotations

from typing import Any

from . import presets as P
from .sampling import largest_remainder, normalize, pick, rng_for

TRIM = (0.2, 5.0)


def effective_margins(preset: str, targets: dict[str, dict[str, float]] | None = None) -> dict[str, dict[str, float]]:
    """Preset margins overridden by user targets (normalized; unknown levels dropped)."""
    margins = {k: dict(v) for k, v in P.PRESETS[preset]["margins"].items()}
    for var, levels in (targets or {}).items():
        if var not in P.TARGETABLE:
            raise ValueError(f"Can't target '{var}'. Targetable: {', '.join(P.TARGETABLE)}")
        clean = {lvl: float(v) for lvl, v in levels.items() if lvl in P.LEVELS[var] and v is not None}
        if not clean or sum(clean.values()) <= 0:
            continue
        total = sum(clean.values())
        margins[var] = {lvl: clean.get(lvl, 0.0) / total for lvl in P.LEVELS[var]}
    return margins


def _conditional(var: str, row: dict) -> list[float]:
    if var == "education":
        return P.EDUCATION_BY_AGE[row["age_band"]]
    if var == "income":
        return P.INCOME_BY_EDUCATION[row["education"]]
    if var == "urbanicity":
        return P.URBANICITY_BY_REGION[row["region"]]
    if var == "party":
        base = P.PARTY_BY_RACE[row["race"]]
        mults = (P.PARTY_AGE_MULT[row["age_band"]], P.PARTY_EDU_MULT[row["education"]], P.PARTY_URBAN_MULT[row["urbanicity"]])
        return [b * a * e * u for b, a, e, u in zip(base, *mults)]
    if var == "lean":
        return P.LEAN_BY_PARTY[row["party"]]
    if var == "ideology":
        return P.IDEOLOGY_BY_PARTY_LEAN[(row["party"], row["lean"])]
    if var == "vote_2024":
        return P.VOTE_BY_LEAN[row["lean"]]
    raise KeyError(var)


def _draw_children(row: dict, uniforms: dict[str, float], tilt: dict[str, list[float]]) -> None:
    for var in P.CHILD_VARS:
        probs = _conditional(var, row)
        if var in tilt:
            probs = [p * t for p, t in zip(probs, tilt[var])]
        row[var] = pick(P.LEVELS[var], probs, uniforms[var])


def _fit_tilt(margins: dict[str, dict[str, float]], seed: Any, size: int = 3000, iterations: int = 10) -> dict[str, list[float]]:
    targeted = [v for v in P.CHILD_VARS if v in margins]
    tilt = {v: [1.0] * len(P.LEVELS[v]) for v in targeted}
    if not targeted:
        return tilt
    rng = rng_for("tilt", seed)
    roots = []
    for _ in range(size):
        row = {v: pick(P.LEVELS[v], [margins[v][lvl] for lvl in P.LEVELS[v]], rng.random()) for v in P.ROOT_VARS}
        roots.append((row, {v: rng.random() for v in P.CHILD_VARS}))
    for _ in range(iterations):
        counts = {v: [0] * len(P.LEVELS[v]) for v in targeted}
        for root, u in roots:
            row = dict(root)
            _draw_children(row, u, tilt)
            for v in targeted:
                counts[v][P.LEVELS[v].index(row[v])] += 1
        worst = 0.0
        for v in targeted:
            achieved = normalize(counts[v])
            for i, lvl in enumerate(P.LEVELS[v]):
                target = margins[v].get(lvl, 0.0)
                worst = max(worst, abs(achieved[i] - target))
                if target <= 0:
                    tilt[v][i] = 0.0
                elif achieved[i] > 0:
                    tilt[v][i] *= target / achieved[i]
                else:
                    tilt[v][i] *= 2.0
        if worst < 0.005:
            break
    return tilt


def _age(band: str, rng) -> int:
    lo, hi = {"18-29": (18, 29), "30-44": (30, 44), "45-64": (45, 64)}.get(band, (65, 90))
    if band == "65+":
        return min(95, 65 + int(rng.expovariate(1 / 9)))
    return rng.randint(lo, hi)


def _turnout(row: dict) -> float:
    base = {"dem": 0.85, "rep": 0.85, "other": 0.7, "nonvoter": 0.3}[row["vote_2024"]]
    base += {"18-29": -0.12, "30-44": -0.05, "45-64": 0.03, "65+": 0.07}[row["age_band"]]
    base += {"hs_or_less": -0.06, "some_college": 0.0, "bachelors": 0.04, "postgrad": 0.06}[row["education"]]
    return round(min(0.98, max(0.05, base)), 2)


def sample(
    n: int,
    preset: str,
    targets: dict[str, dict[str, float]] | None = None,
    oversample: dict[str, dict[str, float]] | None = None,
    seed: Any = 0,
) -> tuple[list[dict], list[float], dict[str, dict[str, float]]]:
    """Return (demographic rows, base weights, margins to rake to)."""
    margins = effective_margins(preset, targets)
    oversample = {v: f for v, f in (oversample or {}).items() if v in P.LEVELS}
    rng = rng_for("sample", seed)

    rows: list[dict] = [{} for _ in range(n)]
    for var in P.ROOT_VARS:
        factors = oversample.get(var, {})
        shares = {lvl: margins[var].get(lvl, 0.0) * factors.get(lvl, 1.0) for lvl in P.LEVELS[var]}
        values = [lvl for lvl, c in largest_remainder(n, shares).items() for _ in range(c)]
        rng.shuffle(values)
        for row, value in zip(rows, values):
            row[var] = value

    tilt = _fit_tilt(margins, seed)
    for var, factors in oversample.items():
        if var in P.CHILD_VARS:
            base = tilt.get(var, [1.0] * len(P.LEVELS[var]))
            tilt[var] = [t * factors.get(lvl, 1.0) for t, lvl in zip(base, P.LEVELS[var])]
    for row in rows:
        _draw_children(row, {v: rng.random() for v in P.CHILD_VARS}, tilt)
        row["age"] = _age(row["age_band"], rng)
        row["turnout"] = _turnout(row)

    weights = []
    for row in rows:
        w = 1.0
        for var, factors in oversample.items():
            f = factors.get(row.get(var), 1.0)
            if f > 0:
                w /= f
        weights.append(w)
    return rows, weights, margins


def rake(
    rows: list[dict],
    base_weights: list[float],
    margins: dict[str, dict[str, float]],
    max_iter: int = 100,
    tol: float = 1e-4,
    trim: tuple[float, float] | None = TRIM,
) -> tuple[list[float], dict]:
    """Iterative proportional fitting of weights to margins. Rows missing a variable are left out of
    that margin only. Returns weights normalized to mean 1 and diagnostics."""
    n = len(rows)
    if n == 0:
        return [], {"converged": True, "iterations": 0, "margins": {}, "deff": 1.0, "n_eff": 0, "trimmed": 0, "warnings": []}
    w = [max(1e-9, x) for x in base_weights]
    warnings: list[str] = []
    usable: dict[str, dict[str, float]] = {}
    for var, target in margins.items():
        present = {r.get(var) for r in rows if r.get(var) is not None}
        if not present:
            warnings.append(f"No agents have a value for {var}; it was not weighted.")
            continue
        missing = [lvl for lvl, t in target.items() if t > 0 and lvl not in present]
        if missing:
            warnings.append(f"No agents in {var} = {', '.join(missing)}; the remaining levels were reweighted.")
        kept = {lvl: t for lvl, t in target.items() if lvl in present}
        total = sum(kept.values())
        if total > 0:
            usable[var] = {lvl: t / total for lvl, t in kept.items()}

    def sweep() -> float:
        for var, target in usable.items():
            sums: dict[str, float] = {}
            known = 0.0
            for r, wi in zip(rows, w):
                lvl = r.get(var)
                if lvl is None:
                    continue
                sums[lvl] = sums.get(lvl, 0.0) + wi
                known += wi
            for i, r in enumerate(rows):
                lvl = r.get(var)
                if lvl is None or sums.get(lvl, 0) <= 0:
                    continue
                w[i] *= target.get(lvl, 0.0) * known / sums[lvl] if target.get(lvl, 0.0) > 0 else 1e-6
        return _max_error(rows, w, usable)

    iterations, err = 0, 0.0
    trimmed = 0
    for _round in range(10):
        for _ in range(max_iter):
            iterations += 1
            err = sweep()
            if err < tol:
                break
        if not trim:
            break
        mean = sum(w) / n
        lo, hi = trim[0] * mean, trim[1] * mean
        clipped = sum(1 for x in w if x < lo or x > hi)
        if not clipped:
            break
        trimmed = clipped
        w[:] = [min(hi, max(lo, x)) for x in w]
    if trim:  # targets that need extreme weights stay unmet rather than letting a few agents dominate
        for _ in range(50):
            mean = sum(w) / n
            lo, hi = trim[0] * mean, trim[1] * mean
            if not any(x < lo * (1 - 1e-9) or x > hi * (1 + 1e-9) for x in w):
                break
            w[:] = [min(hi, max(lo, x)) for x in w]
            err = _max_error(rows, w, usable)
    mean = sum(w) / n
    w = [x / mean for x in w]
    return w, {
        "converged": err < max(tol, 0.005),
        "iterations": iterations,
        "max_error": round(err, 5),
        "margins": composition(rows, w, usable),
        "deff": round(design_effect(w), 3),
        "n_eff": round(n / design_effect(w), 1),
        "trimmed": trimmed,
        "warnings": warnings,
    }


def _max_error(rows: list[dict], w: list[float], margins: dict[str, dict[str, float]]) -> float:
    worst = 0.0
    for var, target in margins.items():
        sums: dict[str, float] = {}
        known = 0.0
        for r, wi in zip(rows, w):
            lvl = r.get(var)
            if lvl is None:
                continue
            sums[lvl] = sums.get(lvl, 0.0) + wi
            known += wi
        for lvl, t in target.items():
            worst = max(worst, abs((sums.get(lvl, 0.0) / known if known else 0.0) - t))
    return worst


def design_effect(w: list[float]) -> float:
    s = sum(w)
    return len(w) * sum(x * x for x in w) / (s * s) if s else 1.0


def composition(rows: list[dict], w: list[float], margins: dict[str, dict[str, float]] | None = None) -> dict:
    """Per variable: target (if any), weighted share and raw share for every level."""
    out: dict[str, dict] = {}
    for var in P.LEVELS:
        known = [(r.get(var), wi) for r, wi in zip(rows, w) if r.get(var) is not None]
        if not known:
            continue
        W = sum(wi for _, wi in known)
        target = (margins or {}).get(var)
        out[var] = {
            lvl: {
                "target": round(target[lvl], 4) if target and lvl in target else None,
                "weighted": round(sum(wi for v, wi in known if v == lvl) / W, 4) if W else 0.0,
                "raw": round(sum(1 for v, _ in known if v == lvl) / len(known), 4),
            }
            for lvl in P.LEVELS[var]
        }
    return out


# ---------------------------------------------------------------- segments

SEGMENT_DIMS = ("party", "lean", "ideology", "age_band", "gender", "race", "education", "urbanicity", "region", "vote_2024")


def segment_levels(demo: dict) -> dict[str, str]:
    """dimension -> level for every segment dimension this agent has a value for."""
    out = {}
    for dim in SEGMENT_DIMS:
        v = demo.get(dim)
        if v is not None:
            out[dim] = v
    edu = demo.get("education")
    if edu is not None:
        out["college"] = "college grad" if edu in ("bachelors", "postgrad") else "non-college"
    return out


def ideology_score(demo: dict) -> float:
    """-1 (liberal) .. +1 (conservative), from ideology and lean."""
    base = {"liberal": -0.7, "moderate": 0.0, "conservative": 0.7}.get(demo.get("ideology") or "moderate", 0.0)
    base += {"dem": -0.2, "rep": 0.2}.get(demo.get("lean") or "none", 0.0)
    return max(-1.0, min(1.0, base))


def summarize_population(rows: list[dict], weights: list[float]) -> dict[str, Any]:
    n = len(rows)
    ages = [r["age"] for r in rows if r.get("age") is not None]
    return {
        "n": n,
        "deff": round(design_effect(weights), 3) if weights else 1.0,
        "n_eff": round(n / design_effect(weights), 1) if weights else n,
        "median_age": sorted(ages)[len(ages) // 2] if ages else None,
        "mean_weight": 1.0,
        "max_weight": round(max(weights), 3) if weights else None,
        "min_weight": round(min(weights), 3) if weights else None,
    }
