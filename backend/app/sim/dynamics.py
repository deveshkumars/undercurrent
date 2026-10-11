"""Emotion, memory and opinion dynamics for social agents (POSIM's deterministic parts).

Order within a tick: decay → LLM call → stimulation → contagion.
- Decay: e(t) = b + (e0 - b)·2^(-Δt/half_life). (POSIM decays toward 0; decaying toward the agent's
  own baseline keeps chronically angry people angry.)
- Stimulation: e ← (1-η)·e + η·e_llm, where e_llm is the emotion state the agent reported after reading.
- Contagion: e ← (1-ρ)·e + ρ·ē_feed, the score-weighted mean emotion expressed in what they just read.
"""

from __future__ import annotations

import re

from .presets import EMOTIONS

DEFAULTS = {"eta": 0.5, "half_life_min": 180.0, "rho": 0.15}
INTENSITY = {"very_low": 0.15, "low": 0.33, "medium": 0.66, "high": 1.0, "very_high": 1.0}
STOP = set("the a an and or but if of to in on for with at by from this that these those it its is are was were be been "
           "have has had not no you your they them their we our i me my he she his her just about what who how why".split())


def params(overrides: dict | None) -> dict[str, float]:
    p = dict(DEFAULTS)
    for k, v in (overrides or {}).items():
        if k in p and v is not None:
            p[k] = float(v)
    return p


def clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def decay(emotion: dict[str, float], baseline: dict[str, float], dt_min: float, half_life: float) -> dict[str, float]:
    f = 2 ** (-max(0.0, dt_min) / half_life)
    return {e: baseline.get(e, 0.0) + (emotion.get(e, 0.0) - baseline.get(e, 0.0)) * f for e in EMOTIONS}


def stimulate(emotion: dict[str, float], reported: dict[str, float], eta: float) -> dict[str, float]:
    return {e: clip01((1 - eta) * emotion.get(e, 0.0) + eta * clip01(reported.get(e, 0.0))) for e in EMOTIONS}


def expressed(post: dict) -> dict[str, float]:
    """One-hot emotion vector scaled by intensity for a post or comment."""
    vec = {e: 0.0 for e in EMOTIONS}
    et = post.get("emotion")
    if et in vec:
        vec[et] = post.get("intensity", 0.5)
    return vec


def contagion(emotion: dict[str, float], feed: list[tuple[dict, float]], rho: float) -> dict[str, float]:
    total = sum(w for _, w in feed)
    if total <= 0:
        return emotion
    mean = {e: sum(expressed(p)[e] * w for p, w in feed) / total for e in EMOTIONS}
    return {e: clip01((1 - rho) * emotion.get(e, 0.0) + rho * mean[e]) for e in EMOTIONS}


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z']{4,}", (text or "").lower()) if t not in STOP}


def remember(memory: list[dict], item: dict, cap: int = 30) -> list[dict]:
    memory = memory + [item]
    if len(memory) > cap:
        now = item["minute"]
        memory.sort(key=lambda m: m["importance"] * 2 ** (-(now - m["minute"]) / 720), reverse=True)
        memory = sorted(memory[:cap], key=lambda m: m["minute"])
    return memory


def recall(memory: list[dict], query_text: str, query_topics: set[str], minute: float, k: int = 5) -> list[dict]:
    """POSIM retrieval: R = α·recency + (1-α)·similarity, α = 0.5, similarity from topic and word overlap."""
    qt = tokens(query_text)
    scored = []
    for m in memory:
        recency = 2 ** (-(minute - m["minute"]) / 720)
        mt = set(m.get("topics", []))
        sim = 0.5 * (len(mt & query_topics) / len(mt | query_topics) if mt and query_topics else 0.0)
        mw = tokens(m["text"])
        sim += 0.5 * (len(mw & qt) / len(mw | qt) if mw and qt else 0.0)
        scored.append((0.5 * recency + 0.5 * sim, m))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:k]]


def upsert_opinions(opinions: list[dict], new: list[dict], minute: float, cap: int = 8) -> list[dict]:
    by_subject = {o["subject"].strip().lower(): o for o in opinions}
    for o in new:
        subj = (o.get("subject") or "").strip()
        if not subj:
            continue
        by_subject[subj.lower()] = {"subject": subj[:80], "opinion": (o.get("opinion") or "")[:240],
                                    "stance": max(-1.0, min(1.0, float(o.get("stance") or 0.0))), "minute": minute}
    return sorted(by_subject.values(), key=lambda o: o["minute"])[-cap:]


def focal_stance(opinions: list[dict], focal: str, default: float) -> float:
    f = focal.strip().lower()
    words = tokens(f)
    for o in reversed(opinions):
        s = o["subject"].lower()
        if f in s or s in f or (words and words & tokens(s)):
            return o["stance"]
    return default


def describe_mood(emotion: dict[str, float]) -> str:
    parts = []
    for e, v in sorted(emotion.items(), key=lambda kv: -kv[1]):
        if v >= 0.15:
            word = "strong" if v >= 0.6 else "moderate" if v >= 0.35 else "mild"
            parts.append(f"{e} {v:.2f} ({word})")
    return ", ".join(parts) or "calm, nothing much"
