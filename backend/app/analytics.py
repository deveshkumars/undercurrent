"""Deterministic polling analytics. Everything here is plain arithmetic so it is testable and
cheap; the LLM layer is handed these numbers rather than asked to compute them.

Method in brief:
  * Each poll's variance = sampling variance p(100-p)/n plus a fixed non-sampling term.
  * Pollster house effects are estimated as shrunken mean residuals against a
    leave-one-out centered average, then centered to sum to zero and subtracted.
  * The polling average is a causal (no look-ahead) inverse-variance average with
    exponential recency decay, so the value on day t uses only polls released by t.
  * An event's impact is the inverse-variance mean of house-adjusted polls in the
    window after it minus the window before it, with a standard error and z-score.
  * Theme / event-type effects pool event impacts by inverse variance.
  * Forecast priors pool impacts of similar past events, shrunk toward zero.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Iterable

DEFAULT_SAMPLE = 800
MAX_SAMPLE = 3000  # cap so one mega-poll can't dominate
NONSAMPLING_SD = 1.5  # pp of error every poll carries regardless of n
HALF_LIFE_DAYS = 7.0
LOOKBACK_DAYS = 30
HOUSE_SHRINK = 3.0  # pseudo-polls pulling each house effect toward 0
EVENT_TAU = 0.75  # pp, how much true effects vary between "similar" events
PRIOR_SD = 1.5  # pp, prior on a single event's effect before seeing analogs

TYPE_FAMILY = {
    "speech": "appearance",
    "town_hall": "appearance",
    "debate": "appearance",
    "interview": "appearance",
    "ad": "messaging",
    "social_post": "messaging",
    "statement": "messaging",
    "policy": "governing",
    "vote": "governing",
}


def _d(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None or math.isnan(x) else round(x, nd)


def poll_variance(value: float, sample_size: int | None) -> float:
    n = min(sample_size or DEFAULT_SAMPLE, MAX_SAMPLE)
    p = min(max(value, 1.0), 99.0)
    return p * (100 - p) / n + NONSAMPLING_SD**2


def _norm_topic(t: str) -> str:
    return " ".join(t.strip().lower().replace("_", " ").split())


# ---------------------------------------------------------------- filtering


def available_dimensions(polls: Iterable[dict]) -> dict[str, list[str]]:
    metrics: dict[str, int] = defaultdict(int)
    segments: dict[str, int] = defaultdict(int)
    for p in polls:
        metrics[p.get("metric") or "vote_share"] += 1
        segments[p.get("segment") or "All"] += 1
    seg_sorted = sorted(segments, key=lambda s: (s != "All", -segments[s], s))
    return {"metrics": sorted(metrics, key=lambda m: -metrics[m]), "segments": seg_sorted}


def select_polls(polls: Iterable[dict], metric: str, segment: str) -> list[dict]:
    out = [
        p
        for p in polls
        if (p.get("metric") or "vote_share") == metric and (p.get("segment") or "All") == segment
    ]
    return sorted(out, key=lambda p: (str(p["date"]), p.get("pollster", "")))


# ---------------------------------------------------------------- house effects


def house_effects(polls: list[dict], field: str = "value") -> dict[str, dict[str, float]]:
    """Shrunken pollster bias relative to a leave-one-out centered average."""
    pts = [(p, _d(p["date"]), p[field]) for p in polls if p.get(field) is not None]
    if len(pts) < 4:
        return {}
    residuals: dict[str, list[float]] = defaultdict(list)
    for i, (p, d, v) in enumerate(pts):
        num = den = 0.0
        for j, (q, dq, vq) in enumerate(pts):
            if i == j or q.get("pollster") == p.get("pollster"):
                continue
            gap = abs((dq - d).days)
            if gap > 21:
                continue
            w = 0.5 ** (gap / HALF_LIFE_DAYS) / poll_variance(vq, q.get("sample_size"))
            num += w * vq
            den += w
        if den > 0:
            residuals[p.get("pollster") or "Unknown"].append(v - num / den)
    raw = {k: sum(r) / (len(r) + HOUSE_SHRINK) for k, r in residuals.items() if len(r) >= 2}
    if not raw:
        return {}
    counts = {k: len(residuals[k]) for k in raw}
    center = sum(raw[k] * counts[k] for k in raw) / sum(counts.values())
    return {k: {"effect": raw[k] - center, "n": counts[k]} for k in raw}


def adjust_polls(polls: list[dict]) -> tuple[list[dict], list[dict]]:
    he_c = house_effects(polls, "value")
    he_o = house_effects(polls, "opponent_value")
    adjusted = []
    for p in polls:
        q = dict(p)
        pollster = p.get("pollster") or "Unknown"
        q["house_effect"] = _r(he_c.get(pollster, {}).get("effect", 0.0))
        q["adj_value"] = p["value"] - he_c.get(pollster, {}).get("effect", 0.0)
        if p.get("opponent_value") is not None:
            q["adj_opponent_value"] = p["opponent_value"] - he_o.get(pollster, {}).get("effect", 0.0)
        adjusted.append(q)
    table = [
        {"pollster": k, "effect": _r(v["effect"]), "n": v["n"]}
        for k, v in sorted(he_c.items(), key=lambda kv: -abs(kv[1]["effect"]))
    ]
    return adjusted, table


# ---------------------------------------------------------------- polling average


def _causal_avg(pts: list[tuple[date, float, float]], t: date) -> tuple[float, float] | None:
    num = den = den_sq_var = 0.0
    for d, v, var in pts:
        age = (t - d).days
        if age < 0:
            break
        if age > LOOKBACK_DAYS:
            continue
        decay = 0.5 ** (age / HALF_LIFE_DAYS)
        w = decay / var
        num += w * v
        den += w
        den_sq_var += w * w * var
    if den == 0:
        return None
    return num / den, math.sqrt(den_sq_var) / den


def polling_average(adjusted: list[dict]) -> list[dict]:
    if not adjusted:
        return []
    cand = sorted(
        ((_d(p["date"]), p["adj_value"], poll_variance(p["value"], p.get("sample_size"))) for p in adjusted),
        key=lambda x: x[0],
    )
    opp = sorted(
        (
            (_d(p["date"]), p["adj_opponent_value"], poll_variance(p["opponent_value"], p.get("sample_size")))
            for p in adjusted
            if p.get("adj_opponent_value") is not None
        ),
        key=lambda x: x[0],
    )
    start, end = cand[0][0], cand[-1][0]
    series = []
    t = start
    while t <= end:
        row: dict[str, Any] = {"date": t.isoformat()}
        c = _causal_avg(cand, t)
        if c:
            row.update(value=_r(c[0]), lo=_r(c[0] - 1.96 * c[1]), hi=_r(c[0] + 1.96 * c[1]), se=_r(c[1], 3))
        o = _causal_avg(opp, t) if opp else None
        if o:
            row.update(opp=_r(o[0]), opp_lo=_r(o[0] - 1.96 * o[1]), opp_hi=_r(o[0] + 1.96 * o[1]))
        if c:
            series.append(row)
        t += timedelta(days=1)
    return series


# ---------------------------------------------------------------- event impact


def _window_mean(pts: list[tuple[date, float, float]], lo: date, hi: date) -> tuple[float, float, int] | None:
    sel = [(v, var) for d, v, var in pts if lo <= d <= hi]
    if not sel:
        return None
    w = [1 / var for _, var in sel]
    mean = sum(wi * v for wi, (v, _) in zip(w, sel)) / sum(w)
    return mean, 1 / sum(w), len(sel)


def _signal(z: float, n_pre: int, n_post: int) -> str:
    if n_pre < 2 or n_post < 2:
        return "insufficient"
    a = abs(z)
    if a >= 2.58:
        return "strong"
    if a >= 1.96:
        return "clear"
    if a >= 1.28:
        return "weak"
    return "none"


def event_impact(
    pts: list[tuple[date, float, float]], event_date: date, window: int
) -> dict[str, Any] | None:
    pre = _window_mean(pts, event_date - timedelta(days=window), event_date - timedelta(days=1))
    post = _window_mean(pts, event_date + timedelta(days=1), event_date + timedelta(days=window))
    if not pre or not post:
        return {
            "delta": None,
            "se": None,
            "z": None,
            "n_pre": pre[2] if pre else 0,
            "n_post": post[2] if post else 0,
            "signal": "insufficient",
        }
    delta = post[0] - pre[0]
    se = math.sqrt(pre[1] + post[1])
    z = delta / se if se else 0.0
    return {
        "pre": _r(pre[0]),
        "post": _r(post[0]),
        "delta": _r(delta),
        "se": _r(se),
        "z": _r(z),
        "n_pre": pre[2],
        "n_post": post[2],
        "signal": _signal(z, pre[2], post[2]),
    }


def _points(adjusted: list[dict]) -> list[tuple[date, float, float]]:
    return sorted(
        ((_d(p["date"]), p["adj_value"], poll_variance(p["value"], p.get("sample_size"))) for p in adjusted),
        key=lambda x: x[0],
    )


def score_events(
    events: list[dict], adjusted: list[dict], window: int, segment_points: dict[str, list] | None = None
) -> list[dict]:
    pts = _points(adjusted)
    ordered = sorted(events, key=lambda e: str(e["date"]))
    out = []
    for ev in ordered:
        d = _d(ev["date"])
        impact = event_impact(pts, d, window)
        overlaps = [
            {"id": o["id"], "title": o["title"], "date": str(o["date"])}
            for o in ordered
            if o["id"] != ev["id"] and abs((_d(o["date"]) - d).days) < window
        ]
        seg_impacts = {}
        for seg, seg_pts in (segment_points or {}).items():
            si = event_impact(seg_pts, d, window)
            if si and si["signal"] != "insufficient":
                seg_impacts[seg] = {k: si[k] for k in ("delta", "se", "z", "signal")}
        out.append({**ev, "date": str(ev["date"]), "impact": impact, "overlaps": overlaps, "segment_impacts": seg_impacts})
    return out


def _pool(items: list[tuple[float, float]]) -> tuple[float, float]:
    w = [1 / (se * se) for _, se in items]
    mean = sum(wi * d for wi, (d, _) in zip(w, items)) / sum(w)
    return mean, math.sqrt(1 / sum(w))


def group_effects(scored: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for ev in scored:
        imp = ev["impact"]
        if not imp or imp["delta"] is None or not imp["se"]:
            continue
        labels = [_norm_topic(t) for t in ev.get("topics", [])] if key == "topics" else [ev.get("type", "other")]
        for label in set(labels):
            if label:
                groups[label].append(ev)
    rows = []
    for label, evs in groups.items():
        mean, se = _pool([(e["impact"]["delta"], e["impact"]["se"]) for e in evs])
        rows.append(
            {
                "label": label,
                "mean_delta": _r(mean),
                "se": _r(se),
                "z": _r(mean / se if se else 0.0),
                "count": len(evs),
                "event_ids": [e["id"] for e in evs],
            }
        )
    return sorted(rows, key=lambda r: -(r["mean_delta"] or 0))


# ---------------------------------------------------------------- summary


def _value_at(series: list[dict], t: date, field: str = "value") -> float | None:
    best = None
    for row in series:
        if _d(row["date"]) <= t and row.get(field) is not None:
            best = row[field]
    return best


def summary_stats(series: list[dict], adjusted: list[dict]) -> dict[str, Any]:
    if not series:
        return {"poll_count": 0}
    last = series[-1]
    end = _d(last["date"])
    vals = [r["value"] for r in series if r.get("value") is not None]
    hi_row = max(series, key=lambda r: r.get("value") or -1)
    lo_row = min(series, key=lambda r: r.get("value") if r.get("value") is not None else 101)
    swings = []
    for i in range(14, len(series)):
        a, b = series[i - 14].get("value"), series[i].get("value")
        if a is not None and b is not None:
            swings.append(b - a)
    vol = math.sqrt(sum(s * s for s in swings) / len(swings)) if swings else None
    v7, v30 = _value_at(series, end - timedelta(days=7)), _value_at(series, end - timedelta(days=30))
    stats = {
        "latest_date": last["date"],
        "latest": last.get("value"),
        "latest_se": last.get("se"),
        "change_7d": _r(last["value"] - v7) if v7 is not None else None,
        "change_30d": _r(last["value"] - v30) if v30 is not None else None,
        "high": {"value": hi_row.get("value"), "date": hi_row["date"]},
        "low": {"value": lo_row.get("value"), "date": lo_row["date"]},
        "mean": _r(sum(vals) / len(vals)),
        "volatility_14d": _r(vol),
        "poll_count": len(adjusted),
        "pollster_count": len({p.get("pollster") for p in adjusted}),
        "first_date": series[0]["date"],
    }
    if last.get("opp") is not None:
        stats["opponent_latest"] = last["opp"]
        stats["margin"] = _r(last["value"] - last["opp"])
        o30 = _value_at(series, end - timedelta(days=30), "opp")
        if o30 is not None and v30 is not None:
            stats["margin_change_30d"] = _r((last["value"] - last["opp"]) - (v30 - o30))
    return stats


# ---------------------------------------------------------------- top-level


def analyze(
    polls: list[dict], events: list[dict], metric: str = "vote_share", segment: str = "All", window: int = 14
) -> dict[str, Any]:
    dims = available_dimensions(polls)
    if metric not in dims["metrics"] and dims["metrics"]:
        metric = dims["metrics"][0]
    selected = select_polls(polls, metric, segment)
    adjusted, house_table = adjust_polls(selected)
    series = polling_average(adjusted)

    seg_points = {}
    for seg in dims["segments"]:
        if seg == segment:
            continue
        seg_polls = select_polls(polls, metric, seg)
        if len(seg_polls) >= 4:
            seg_adj, _ = adjust_polls(seg_polls)
            seg_points[seg] = _points(seg_adj)

    scored = score_events(events, adjusted, window, seg_points)
    return {
        "metric": metric,
        "segment": segment,
        "window_days": window,
        "dimensions": dims,
        "stats": summary_stats(series, adjusted),
        "trend": series,
        "polls": [
            {k: p.get(k) for k in ("id", "date", "pollster", "sample_size", "population", "value", "opponent_value", "house_effect")}
            | {"adj_value": _r(p["adj_value"]), "adj_opponent_value": _r(p.get("adj_opponent_value"))}
            for p in adjusted
        ],
        "house_effects": house_table,
        "events": scored,
        "themes": group_effects(scored, "topics"),
        "event_types": group_effects(scored, "type"),
    }


def find_analogs(
    scored_events: list[dict], topics: list[str], event_type: str, k: int = 6
) -> dict[str, Any]:
    """Similar past events and a shrunken, precision-weighted prior for a new event's effect."""
    want = {_norm_topic(t) for t in topics if t.strip()}
    fam = TYPE_FAMILY.get(event_type, event_type)
    candidates = []
    for ev in scored_events:
        imp = ev.get("impact") or {}
        if imp.get("delta") is None or imp.get("signal") == "insufficient":
            continue
        have = {_norm_topic(t) for t in ev.get("topics", [])}
        topic_sim = len(want & have) / len(want | have) if (want or have) else 0.0
        if ev.get("type") == event_type:
            type_sim = 1.0
        elif TYPE_FAMILY.get(ev.get("type", ""), ev.get("type")) == fam:
            type_sim = 0.5
        else:
            type_sim = 0.0
        sim = 0.65 * topic_sim + 0.35 * type_sim
        if sim >= 0.15:
            candidates.append((sim, ev))
    candidates.sort(key=lambda x: -x[0])
    top = candidates[:k]

    precision = 1 / PRIOR_SD**2
    weighted = 0.0
    for sim, ev in top:
        p = sim / (ev["impact"]["se"] ** 2 + EVENT_TAU**2)
        precision += p
        weighted += p * ev["impact"]["delta"]
    mean = weighted / precision
    pred_sd = math.sqrt(1 / precision + EVENT_TAU**2)
    return {
        "analogs": [
            {
                "id": ev["id"],
                "title": ev["title"],
                "date": ev["date"],
                "type": ev.get("type"),
                "topics": ev.get("topics", []),
                "similarity": _r(sim),
                "delta": ev["impact"]["delta"],
                "se": ev["impact"]["se"],
                "signal": ev["impact"]["signal"],
                "segment_impacts": ev.get("segment_impacts", {}),
            }
            for sim, ev in top
        ],
        "prior_mean": _r(mean),
        "prior_sd": _r(pred_sd),
        "range_80": [_r(mean - 1.2816 * pred_sd), _r(mean + 1.2816 * pred_sd)],
        "evidence_weight": _r(precision - 1 / PRIOR_SD**2, 3),
    }
