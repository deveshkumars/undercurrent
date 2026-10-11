"""Deterministic statistics for simulation results (pure Python; no numpy needed).

Panel: every agent answers under every arm, so treatment effects are paired differences
d_i = y_i(treatment) - y_i(control), weighted by survey weights. Whole-sample intervals use a
percentile bootstrap over agents; segment cells use a linearized (sandwich) standard error and
Benjamini-Hochberg across cells. These intervals measure simulation noise only.
"""

from __future__ import annotations

import math
import random
from operator import mul
from typing import Any, Iterable

Z975 = 1.959964


def t975(df: float) -> float:
    """Approximate 97.5th percentile of Student's t (Cornish-Fisher expansion)."""
    if df <= 0:
        return float("nan")
    if df > 200:
        return Z975
    z = Z975
    return z + (z**3 + z) / (4 * df) + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * df**2)


def p_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def wmean(xs: Iterable[float], ws: Iterable[float]) -> float | None:
    num = den = 0.0
    for x, w in zip(xs, ws):
        num += x * w
        den += w
    return num / den if den > 0 else None


def wsd(xs: list[float], ws: list[float]) -> float | None:
    m = wmean(xs, ws)
    if m is None or len(xs) < 2:
        return None
    den = sum(ws)
    return math.sqrt(sum(w * (x - m) ** 2 for x, w in zip(xs, ws)) / den)


def n_eff(ws: list[float]) -> float:
    s2 = sum(w * w for w in ws)
    return (sum(ws) ** 2) / s2 if s2 > 0 else 0.0


def linearized(ds: list[float], ws: list[float]) -> dict[str, Any]:
    """Weighted mean of ds with a sandwich SE, t interval and normal p-value."""
    n = len(ds)
    m = wmean(ds, ws)
    if m is None or n < 2:
        return {"est": m, "se": None, "lo": None, "hi": None, "p": None, "n": n, "n_eff": round(n_eff(ws), 1)}
    W = sum(ws)
    se = math.sqrt(n / (n - 1) * sum((w * (d - m)) ** 2 for d, w in zip(ds, ws))) / W
    ne = n_eff(ws)
    t = t975(max(1.0, ne - 1))
    p = p_two_sided(m / se) if se > 0 else (1.0 if m == 0 else 0.0)
    return {"est": m, "se": se, "lo": m - t * se, "hi": m + t * se, "p": p, "n": n, "n_eff": round(ne, 1)}


def bootstrap(stats: dict[str, tuple[list[float], list[float]]], n: int, B: int, rng: random.Random) -> dict[str, tuple[float, float]]:
    """Percentile intervals for several weighted means at once, resampling the same agents for all.

    ``stats[key] = (values, weights)`` with one entry per agent (weight 0 where missing)."""
    if n < 2 or not stats:
        return {k: (math.nan, math.nan) for k in stats}
    B = max(200, min(B, int(8e6 / (n * len(stats)))))  # keep finalize fast for big panels
    prepared = {k: ([v * w for v, w in zip(vals, ws)], ws) for k, (vals, ws) in stats.items()}
    draws: dict[str, list[float]] = {k: [] for k in stats}
    idx = range(n)
    for _ in range(B):
        counts = [0] * n
        for i in rng.choices(idx, k=n):
            counts[i] += 1
        for k, (wx, ws) in prepared.items():
            den = sum(map(mul, counts, ws))
            if den > 0:
                draws[k].append(sum(map(mul, counts, wx)) / den)
    out = {}
    for k, xs in draws.items():
        if len(xs) < 20:
            out[k] = (math.nan, math.nan)
            continue
        xs.sort()
        out[k] = (xs[int(0.025 * (len(xs) - 1))], xs[int(math.ceil(0.975 * (len(xs) - 1)))])
    return out


def benjamini_hochberg(pvals: list[float | None], q: float = 0.10) -> list[bool]:
    """Which hypotheses survive the BH false discovery rate procedure."""
    indexed = sorted((p, i) for i, p in enumerate(pvals) if p is not None)
    m = len(indexed)
    passed = [False] * len(pvals)
    cutoff = -1
    for rank, (p, _) in enumerate(indexed, 1):
        if p <= q * rank / m:
            cutoff = rank
    for rank, (_, i) in enumerate(indexed, 1):
        if rank <= cutoff:
            passed[i] = True
    return passed


def r(x: float | None, nd: int = 2) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(x, nd)


# ---------------------------------------------------------------- panel answers


def ordinal_score(options: list[str], answer: str) -> float | None:
    """Ordinal options run from most positive to most negative; map onto 100..0."""
    if answer not in options or len(options) < 2:
        return None
    return 100.0 * (len(options) - 1 - options.index(answer)) / (len(options) - 1)


def numeric_value(q: dict, answer: Any) -> float | None:
    if answer is None:
        return None
    if q["kind"] == "scale":
        try:
            x = float(answer)
        except (TypeError, ValueError):
            return None
        return float(min(q["scale_max"], max(q["scale_min"], round(x))))
    if q["kind"] == "single_choice" and q.get("ordinal"):
        return ordinal_score(q["options"], answer)
    return None


def is_numeric(q: dict) -> bool:
    return q["kind"] == "scale" or (q["kind"] == "single_choice" and bool(q.get("ordinal")))


def agent_records(
    responses: list[dict], agents: dict[str, dict], questions: list[dict], weight_key: str, likely_voter: bool, control_id: str,
) -> list[dict]:
    """Collapse replicate responses into one record per agent: numeric means, choice fractions, texts."""
    by_agent: dict[str, list[dict]] = {}
    for resp in responses:
        if resp.get("status") == "ok":
            by_agent.setdefault(resp["agent_id"], []).append(resp)
    records = []
    for aid, resps in by_agent.items():
        agent = agents.get(aid)
        if not agent:
            continue
        w = agent.get(weight_key) if agent.get(weight_key) is not None else agent.get("weight", 1.0)
        rec: dict[str, Any] = {"id": aid, "w": float(w or 0.0), "num": {}, "cat": {}, "open": {}, "reasoning": {}}
        for resp in resps:
            arm = resp["arm_id"]
            ans = resp.get("answers") or {}
            for q in questions:
                a = ans.get(q["id"])
                if q["kind"] == "open":
                    if a:
                        rec["open"].setdefault(arm, {}).setdefault(q["id"], []).append(str(a))
                    continue
                if q["kind"] == "single_choice" and a in q["options"]:
                    rec["cat"].setdefault(arm, {}).setdefault(q["id"], []).append(a)
                v = numeric_value(q, a)
                if v is not None:
                    rec["num"].setdefault(arm, {}).setdefault(q["id"], []).append(v)
            if resp.get("reasoning"):
                rec["reasoning"].setdefault(arm, []).append(resp["reasoning"])
        rec["num"] = {arm: {q: sum(v) / len(v) for q, v in qs.items()} for arm, qs in rec["num"].items()}
        rec["cat"] = {
            arm: {q: {opt: vals.count(opt) / len(vals) for opt in set(vals)} for q, vals in qs.items()}
            for arm, qs in rec["cat"].items()
        }
        if likely_voter:
            t = rec["num"].get(control_id, {}).get("turnout")
            if t is not None:
                rec["w"] *= max(0.0, min(1.0, t / 10.0))
        records.append(rec)
    return records


def toplines(records: list[dict], questions: list[dict], arm_ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for arm in arm_ids:
        per_q: dict[str, Any] = {}
        for q in questions:
            if q["kind"] == "open":
                continue
            entry: dict[str, Any] = {}
            if is_numeric(q):
                pairs = [(rec["num"][arm][q["id"]], rec["w"]) for rec in records if q["id"] in rec["num"].get(arm, {})]
                if pairs:
                    xs, ws = [p[0] for p in pairs], [p[1] for p in pairs]
                    entry.update(mean=r(wmean(xs, ws)), sd=r(wsd(xs, ws)), n=len(xs))
                    if q["kind"] == "scale":
                        lo, hi = q["scale_min"], q["scale_max"]
                        bins = 10 if hi - lo >= 10 else hi - lo + 1
                        width = (hi - lo) / bins if bins else 1
                        hist = [0.0] * bins
                        W = sum(ws)
                        for x, w in pairs:
                            b = min(bins - 1, int((x - lo) / width)) if width else 0
                            hist[b] += w / W if W else 0
                        entry["hist"] = [r(h, 4) for h in hist]
            if q["kind"] == "single_choice":
                pairs2 = [(rec["cat"][arm][q["id"]], rec["w"]) for rec in records if q["id"] in rec["cat"].get(arm, {})]
                W = sum(w for _, w in pairs2)
                entry["shares"] = {
                    opt: r(sum(fr.get(opt, 0.0) * w for fr, w in pairs2) / W if W else None, 4) for opt in q["options"]
                }
                entry["n"] = len(pairs2)
            per_q[q["id"]] = entry
        out[arm] = per_q
    return out


def _paired(records: list[dict], q: dict, treat: str, control: str, opt: str | None = None) -> tuple[list[float], list[float], list[int]]:
    """Per-agent differences (treatment - control) and weights; indices of contributing records."""
    ds, ws, idx = [], [], []
    for i, rec in enumerate(records):
        if opt is None:
            a, b = rec["num"].get(treat, {}).get(q["id"]), rec["num"].get(control, {}).get(q["id"])
        else:
            ta, cb = rec["cat"].get(treat, {}).get(q["id"]), rec["cat"].get(control, {}).get(q["id"])
            a = None if ta is None else 100.0 * ta.get(opt, 0.0)
            b = None if cb is None else 100.0 * cb.get(opt, 0.0)
        if a is None or b is None or rec["w"] <= 0:
            continue
        ds.append(a - b)
        ws.append(rec["w"])
        idx.append(i)
    return ds, ws, idx


def paired_effects(
    records: list[dict], questions: list[dict], treatments: list[str], control: str, seed: Any = 0, B: int = 400,
) -> dict[str, dict[str, Any]]:
    """Whole-sample paired effects with bootstrap intervals. Choice effects are in percentage points."""
    rng = random.Random(str(seed))
    n = len(records)
    stats: dict[str, tuple[list[float], list[float]]] = {}
    lin: dict[str, dict] = {}
    for t in treatments:
        for q in questions:
            keys: list[tuple[str, str | None]] = []
            if is_numeric(q):
                keys.append((f"{t}|{q['id']}|", None))
            if q["kind"] == "single_choice":
                keys += [(f"{t}|{q['id']}|{opt}", opt) for opt in q["options"]]
            for key, opt in keys:
                ds, ws, idx = _paired(records, q, t, control, opt)
                full_v, full_w = [0.0] * n, [0.0] * n
                for d, w, i in zip(ds, ws, idx):
                    full_v[i], full_w[i] = d, w
                stats[key] = (full_v, full_w)
                lin[key] = linearized(ds, ws)
    boots = bootstrap(stats, n, B, rng)
    out: dict[str, dict[str, Any]] = {t: {} for t in treatments}
    for key, l in lin.items():
        t, qid, opt = key.split("|", 2)
        lo, hi = boots.get(key, (math.nan, math.nan))
        cell = {"est": r(l["est"]), "lo": r(lo), "hi": r(hi), "se": r(l["se"], 3), "p": r(l["p"], 4), "n": l["n"]}
        if opt:
            out[t].setdefault(qid, {}).setdefault("options", {})[opt] = cell
        else:
            out[t].setdefault(qid, {}).update(cell)
    return out


def segment_effects(
    records: list[dict], segs: dict[str, dict[str, str]], q: dict, treatments: list[str], control: str,
    opt: str | None = None, min_n: int = 20,
) -> list[dict]:
    """Effect of each treatment on one outcome within every segment level, with BH flags across cells."""
    cells: list[dict] = []
    dims: dict[str, set[str]] = {}
    for rec in records:
        for dim, lvl in segs.get(rec["id"], {}).items():
            dims.setdefault(dim, set()).add(lvl)
    for t in treatments:
        ds_all, ws_all, idx_all = _paired(records, q, t, control, opt)
        for dim in sorted(dims):
            for lvl in sorted(dims[dim]):
                ds = [d for d, i in zip(ds_all, idx_all) if segs.get(records[i]["id"], {}).get(dim) == lvl]
                ws = [w for w, i in zip(ws_all, idx_all) if segs.get(records[i]["id"], {}).get(dim) == lvl]
                if not ds:
                    continue
                lin = linearized(ds, ws)
                base_vals, base_ws = [], []
                for i in idx_all:
                    if segs.get(records[i]["id"], {}).get(dim) != lvl:
                        continue
                    rec = records[i]
                    if opt is None:
                        v = rec["num"].get(control, {}).get(q["id"])
                    else:
                        fr = rec["cat"].get(control, {}).get(q["id"])
                        v = None if fr is None else 100.0 * fr.get(opt, 0.0)
                    if v is not None:
                        base_vals.append(v)
                        base_ws.append(rec["w"])
                cells.append({
                    "treatment": t, "dim": dim, "level": lvl,
                    "est": r(lin["est"]), "lo": r(lin["lo"]), "hi": r(lin["hi"]), "se": r(lin["se"], 3),
                    "p": lin["p"], "n": lin["n"], "n_eff": lin["n_eff"],
                    "control_mean": r(wmean(base_vals, base_ws)),
                    "small": lin["n"] < min_n or (lin["n_eff"] or 0) < 10,
                })
    flags = benjamini_hochberg([c["p"] for c in cells])
    for c, f in zip(cells, flags):
        c["fdr"] = bool(f)
        c["p"] = r(c["p"], 4)
    return cells


def transitions(records: list[dict], q: dict, treat: str, control: str) -> dict[str, dict[str, float]]:
    """Weighted control -> treatment answer flows for one choice question (rows sum to 1)."""
    mat: dict[str, dict[str, float]] = {o: {p: 0.0 for p in q["options"]} for o in q["options"]}
    row_tot = {o: 0.0 for o in q["options"]}
    for rec in records:
        c = rec["cat"].get(control, {}).get(q["id"])
        t = rec["cat"].get(treat, {}).get(q["id"])
        if not c or not t:
            continue
        for co, cf in c.items():
            for to, tf in t.items():
                mat[co][to] += rec["w"] * cf * tf
            row_tot[co] += rec["w"] * cf
    return {
        o: {p: r(v / row_tot[o], 4) if row_tot[o] else None for p, v in row.items()}  # type: ignore[misc]
        for o, row in mat.items()
    } | {"_row_share": {o: r(row_tot[o] / (sum(row_tot.values()) or 1), 4) for o in q["options"]}}  # type: ignore[dict-item]


# ---------------------------------------------------------------- social


def valence(emotion_type: str | None, intensity: float) -> float:
    sign = {"happy": 1.0, "surprise": 0.0, "neutral": 0.0, "sad": -1.0, "angry": -1.0, "fear": -1.0, "disgust": -1.0}
    return sign.get(emotion_type or "neutral", 0.0) * intensity


def emotional_concentration(counts: dict[str, float]) -> float | None:
    """POSIM's polarization index PI = 1 - H/H_max over the six emotion proportions."""
    total = sum(counts.values())
    if total <= 0:
        return None
    ps = [c / total for c in counts.values() if c > 0]
    h = -sum(p * math.log(p) for p in ps)
    return 1 - h / math.log(6)


def stance_polarization(stances: list[float]) -> float | None:
    """4 * p(+) * p(-): 1 when the room splits evenly into two committed camps, 0 when one side is absent."""
    if not stances:
        return None
    pos = sum(1 for s in stances if s > 0.5) / len(stances)
    neg = sum(1 for s in stances if s < -0.5) / len(stances)
    return 4 * pos * neg


def cascade_histogram(sizes: list[int]) -> dict[str, int]:
    bins = [("1", 1, 1), ("2", 2, 2), ("3-4", 3, 4), ("5-8", 5, 8), ("9-16", 9, 16), ("17+", 17, 10**9)]
    return {label: sum(1 for s in sizes if lo <= s <= hi) for label, lo, hi in bins}
