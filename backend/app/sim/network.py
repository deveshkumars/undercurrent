"""Follower graph for the social simulation: homophily plus preferential attachment.

Opinion leaders (~5%) are the most active, extraverted heavy users; three media accounts span the
left-center-right range; official accounts (the subject, or the candidate and opponent) post only
through interventions. Edges are "i follows j".
"""

from __future__ import annotations

import math
from typing import Any

from . import demographics as D
from .sampling import rng_for

MEDIA = [
    ("media_left", "The Progressive Wire", -0.7),
    ("media_center", "Daily Ledger News", 0.0),
    ("media_right", "Liberty Post", 0.7),
]


def _homophily(a: dict, b: dict) -> float:
    h = 0.0
    if a.get("party") and a.get("party") == b.get("party"):
        h += 0.4
    h += 0.2 * (1 - abs(a["slant"] - b["slant"]) / 2)
    if a.get("age_band") and a.get("age_band") == b.get("age_band"):
        h += 0.15
    if a.get("region") and a.get("region") == b.get("region"):
        h += 0.15
    if a.get("education") and a.get("education") == b.get("education"):
        h += 0.1
    return h


def build(agents: list[dict], officials: list[tuple[str, str]], seed: Any) -> dict[str, dict]:
    """agents: full agent docs. officials: [(account_id, display name)]. Returns accounts by id."""
    rng = rng_for("network", seed)
    accounts: dict[str, dict] = {}
    for a in agents:
        demo, traits = a.get("demographics", {}), a.get("traits", {})
        accounts[a["id"]] = {
            "id": a["id"], "agent_id": a["id"], "name": a.get("first_name") or "user", "role": "ordinary",
            "party": demo.get("party"), "age_band": demo.get("age_band"), "region": demo.get("region"),
            "education": demo.get("education"), "slant": D.ideology_score(demo),
            "activity": float(traits.get("activity") or 1.0), "extraversion": float((traits.get("big5") or {}).get("E", 0.5)),
            "social_media_use": traits.get("social_media_use", "daily"), "follows": [], "followers": 0,
        }
    # opinion leaders: the top 5% by activity x extraversion among daily/hourly users
    pool = [acc for acc in accounts.values() if acc["social_media_use"] in ("daily", "hourly")]
    pool.sort(key=lambda acc: acc["activity"] * (0.5 + acc["extraversion"]) * rng.uniform(0.8, 1.2), reverse=True)
    for acc in pool[: max(1, math.ceil(0.05 * len(accounts)))]:
        acc["role"] = "opinion_leader"
        acc["activity"] *= 2.0
    for mid, name, slant in MEDIA:
        accounts[mid] = {"id": mid, "agent_id": None, "name": name, "role": "media", "party": None, "age_band": None,
                         "region": None, "education": None, "slant": slant, "activity": 3.0, "extraversion": 0.5,
                         "social_media_use": "hourly", "follows": [], "followers": 0}
    for oid, name in officials:
        accounts[oid] = {"id": oid, "agent_id": None, "name": name, "role": "official", "party": None, "age_band": None,
                         "region": None, "education": None, "slant": 0.0, "activity": 0.0, "extraversion": 0.5,
                         "social_media_use": "daily", "follows": [], "followers": 0}

    popularity = {aid: {"opinion_leader": 10.0, "media": 20.0, "official": 5.0}.get(acc["role"], 0.0) for aid, acc in accounts.items()}
    people = [aid for aid, acc in accounts.items() if acc["agent_id"]]
    M = len(people)
    order = list(people)
    rng.shuffle(order)
    median_deg = min(15.0, max(3.0, M / 6))
    for aid in order:
        me = accounts[aid]
        k = int(round(math.exp(rng.gauss(math.log(median_deg), 0.5))))
        k = max(3, min(k, max(3, M // 3)))
        cands = [bid for bid in accounts if bid != aid]
        keyed = []
        for bid in cands:
            att = (1 + popularity[bid]) ** 0.8 * math.exp(2 * _homophily(me, accounts[bid]))
            keyed.append((rng.random() ** (1 / att), bid))
        keyed.sort(reverse=True)
        chosen = [bid for _, bid in keyed[:k]]
        # everyone follows at least the media account closest to their slant
        nearest_media = min((m for m, _, _ in MEDIA), key=lambda m: abs(accounts[m]["slant"] - me["slant"]))
        if nearest_media not in chosen:
            chosen.append(nearest_media)
        for bid in chosen:
            me["follows"].append(bid)
            popularity[bid] += 1
            other = accounts[bid]
            if other["agent_id"] and other["role"] == "ordinary" and rng.random() < 0.25 and aid not in other["follows"]:
                other["follows"].append(aid)
                popularity[aid] += 1
    for oid, _ in officials:  # people who follow the news also follow the officials, sometimes
        for aid in people:
            if rng.random() < 0.2:
                accounts[aid]["follows"].append(oid)
    for acc in accounts.values():
        acc["follows"] = sorted(set(acc["follows"]))
    for acc in accounts.values():
        for bid in acc["follows"]:
            accounts[bid]["followers"] += 1
    return accounts


def summary(accounts: dict[str, dict]) -> dict[str, Any]:
    people = [a for a in accounts.values() if a["agent_id"]]
    same = total = 0
    for a in people:
        for bid in a["follows"]:
            b = accounts[bid]
            if b["agent_id"] and a.get("party") and b.get("party"):
                total += 1
                same += a["party"] == b["party"]
    degs = sorted(len(a["follows"]) for a in people)
    roles: dict[str, int] = {}
    for a in accounts.values():
        roles[a["role"]] = roles.get(a["role"], 0) + 1
    top = sorted(accounts.values(), key=lambda a: -a["followers"])[:12]
    return {
        "accounts": len(accounts),
        "roles": roles,
        "median_following": degs[len(degs) // 2] if degs else 0,
        "same_party_follow_share": round(same / total, 3) if total else None,
        "top_accounts": [{"id": a["id"], "name": a["name"], "role": a["role"], "party": a.get("party"),
                          "followers": a["followers"]} for a in top],
    }
