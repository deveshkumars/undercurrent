"""Personalized feeds (POSIM's recommender): S = w_h·H + w_p·V + w_r·F.

H (homophily) stands in for embedding similarity with stance, ideology and topic overlap, since the
app has no embedding model. V is normalized engagement, F exponential freshness. A share of slots
(r_explore) is random, the rest split between the relationship channel (accounts you follow, or
posts they reposted) and the public channel.
"""

from __future__ import annotations

import math
import random

DEFAULTS = {"k": 10, "n_comments": 5, "w_h": 0.3, "w_p": 0.3, "w_r": 0.4, "r_explore": 0.2, "window_hours": 24,
            "tau_fresh_min": 120}
ROOT_TYPES = ("short_post", "long_post", "repost_with_comment")
COMMENT_TYPES = ("short_comment", "long_comment")


def params(overrides: dict | None) -> dict[str, float]:
    p = dict(DEFAULTS)
    for k, v in (overrides or {}).items():
        if k in p and v is not None:
            p[k] = float(v)
    return p


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def engagement(post: dict) -> float:
    return post.get("likes", 0) + 2 * post.get("reposts", 0) + 1.5 * post.get("comments", 0)


def build(
    state: dict, acct_id: str, minute: float, p: dict[str, float], rng: random.Random,
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Return (feed posts in display order, comments by post id). Marks shown posts as seen."""
    accounts = state["accounts"]
    me = accounts[acct_id]
    ag = state["agents"].get(acct_id, {})
    seen = set(ag.get("seen", []))
    follows = set(me.get("follows", []))
    posts = state["posts"]
    window = p["window_hours"] * 60
    reposted_by: dict[str, list[str]] = {}
    for post in posts:
        if post["type"] == "repost" and post["author"] in follows and minute - post["minute"] <= window:
            reposted_by.setdefault(post["root"], []).append(post["author"])
    pool = [
        post for post in posts
        if post["type"] in ROOT_TYPES and post["author"] != acct_id and post["id"] not in seen
        and 0 <= minute - post["minute"] <= window
    ]
    if not pool:
        return [], {}
    my_stance = ag.get("stance", 0.0)
    my_topics = set(ag.get("topics", []))
    max_e = max((engagement(x) for x in pool), default=0.0)

    def score(post: dict) -> float:
        author = accounts.get(post["author"], {})
        h = 0.5 * (1 - abs(my_stance - post.get("stance", 0.0)) / 2) \
            + 0.25 * (1 - abs(me.get("slant", 0.0) - author.get("slant", 0.0)) / 2) \
            + 0.25 * jaccard(my_topics, set(post.get("topics", [])))
        v = math.log1p(engagement(post)) / math.log1p(max_e) if max_e > 0 else 0.0
        f = math.exp(-(minute - post["minute"]) / p["tau_fresh_min"])
        return p["w_h"] * h + p["w_p"] * v + p["w_r"] * f

    k = int(p["k"])
    k_exp = int(round(p["r_explore"] * k))
    rel = [x for x in pool if x["author"] in follows or x["id"] in reposted_by]
    pub = [x for x in pool if not (x["author"] in follows or x["id"] in reposted_by)]
    rel.sort(key=score, reverse=True)
    pub.sort(key=score, reverse=True)
    k_rel = math.ceil(0.6 * (k - k_exp))
    chosen = rel[:k_rel]
    k_pub = k - k_exp - len(chosen)
    chosen += pub[:k_pub]
    if len(chosen) < k - k_exp:  # cross-fill when one channel runs short
        extra = [x for x in rel[k_rel:] if x not in chosen]
        chosen += extra[: k - k_exp - len(chosen)]
    leftovers = [x for x in pool if x not in chosen]
    explore = rng.sample(leftovers, min(k_exp, len(leftovers)))
    ranked = sorted(chosen, key=score, reverse=True)
    for i, x in enumerate(explore):  # explore items go mid-feed (positions 3 and 7)
        ranked.insert(min(len(ranked), 2 + 4 * i), x)
    feed = []
    for x in ranked[:k]:
        item = dict(x)
        if x["id"] in reposted_by:
            item["reposted_by"] = [accounts[a]["name"] for a in reposted_by[x["id"]][:2]]
        feed.append(item)

    comments: dict[str, list[dict]] = {}
    nc = int(p["n_comments"])
    by_parent: dict[str, list[dict]] = {}
    for c in posts:
        if c["type"] in COMMENT_TYPES and c["minute"] <= minute:
            by_parent.setdefault(c["parent"], []).append(c)
    for item in feed:
        cs = by_parent.get(item["id"], [])
        if not cs:
            continue
        top = sorted(cs, key=engagement, reverse=True)[:3]
        newest = sorted((c for c in cs if c not in top), key=lambda c: -c["minute"])[: max(0, nc - len(top))]
        comments[item["id"]] = top + newest

    ag["seen"] = (ag.get("seen", []) + [x["id"] for x in feed])[-400:]
    return feed, comments


def trending(posts: list[dict], minute: float, n: int = 5) -> list[str]:
    scores: dict[str, float] = {}
    for x in posts:
        age = minute - x["minute"]
        if 0 <= age <= 120:
            for t in x.get("topics", []):
                t = t.strip().lower().lstrip("#")
                if t:
                    scores[t] = scores.get(t, 0.0) + math.exp(-age / 60) * (1 + math.log1p(engagement(x)))
    return [f"#{t}" for t, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:n]]


def render(feed: list[dict], comments: dict[str, list[dict]], accounts: dict[str, dict], minute: float) -> str:
    if not feed:
        return "(Your feed has nothing new right now.)"
    role_label = {"opinion_leader": "popular account", "media": "news outlet", "official": "official account"}
    lines = []
    for x in feed:
        author = accounts.get(x["author"], {})
        role = role_label.get(author.get("role", ""), "")
        age = int(minute - x["minute"])
        when = f"{age}m ago" if age < 120 else f"{age // 60}h ago"
        via = f" · reposted by {', '.join(x['reposted_by'])}" if x.get("reposted_by") else ""
        head = f"[{x['id']}] @{author.get('name', '?')}{f' ({role})' if role else ''} · {when} · ♥{x.get('likes', 0)} ⟲{x.get('reposts', 0)} 💬{x.get('comments', 0)}{via}"
        lines.append(head)
        if x["type"] == "repost_with_comment" and x.get("quoted_text"):
            lines.append(f"{x['text']}\n  » quoting: {x['quoted_text'][:240]}")
        else:
            lines.append(x["text"])
        for c in comments.get(x["id"], []):
            ca = accounts.get(c["author"], {})
            lines.append(f"   ↳ [{c['id']}] @{ca.get('name', '?')}: {c['text'][:280]}")
        lines.append("")
    return "\n".join(lines).strip()
