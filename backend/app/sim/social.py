"""Social spread (POSIM, 2026): Social-BDI agents on a simulated microblog.

Each tick: apply due interventions → Hawkes intensity → sample active accounts → build personalized
feeds → one structured LLM call per activation (perception → belief → desire → actions) → apply
actions, emotion stimulation and contagion → record metrics. The state is checkpointed every hour of
simulated time; a branch copies a checkpoint and adds interventions, alongside a no-change control
branch from the same checkpoint so run-to-run LLM noise isn't mistaken for an effect.
"""

from __future__ import annotations

import copy
import logging
import math
import re
from typing import Any

from fastapi import HTTPException

from .. import llm
from ..config import get_settings
from ..models import new_id
from ..storage import get_store
from . import costs, dynamics, feed, hawkes, metrics, network
from . import prompts as SP
from .models import BranchIn, Intervention, SocialIn
from .runner import StepCtx, new_run
from .sampling import poisson, rng_for, weighted_sample
from .schemas import SocialActivation

log = logging.getLogger("undercurrent.sim")

INT = {"low": 0.33, "medium": 0.66, "high": 1.0}
CONTENT_TYPES = ("short_post", "long_post", "repost_with_comment", "short_comment", "long_comment")
TEXT_LIMIT = {"short_post": 280, "short_comment": 280, "repost_with_comment": 600, "long_post": 1200, "long_comment": 1200}
NEGATIVE = ("sad", "angry", "fear", "disgust")

TEMPLATES: list[dict] = [
    {"id": "swift_apology", "label": "Swift apology", "description": "The official account apologizes within the hour and says what it will fix.",
     "interventions": [{"offset_min": 30, "kind": "event", "event": {"author": "official", "importance": 1.0, "topics": [],
                        "text": "We hear you, and we got this wrong. We're sorry. Here is what we're doing about it, starting today: …"}}]},
    {"id": "proactive_transparency", "label": "Proactive transparency", "description": "Official facts early, then a detailed follow-up six hours later.",
     "interventions": [
         {"offset_min": 30, "kind": "event", "event": {"author": "official", "importance": 1.0, "topics": [],
                                                      "text": "Here are the facts as we know them right now: … We'll share a full update by tonight."}},
         {"offset_min": 360, "kind": "event", "event": {"author": "official", "importance": 0.8, "topics": [],
                                                       "text": "Full update, with the documents: …"}}]},
    {"id": "dialogue", "label": "Dialogue with critics", "description": "The official account answers the most common criticisms directly.",
     "interventions": [{"offset_min": 60, "kind": "event", "event": {"author": "official", "importance": 0.8, "topics": [],
                        "text": "A lot of you asked the same questions today. Straight answers: 1) … 2) … 3) …"}}]},
    {"id": "fact_check", "label": "Independent fact-check", "description": "A centrist outlet publishes a fact-check.",
     "interventions": [{"offset_min": 120, "kind": "event", "event": {"author": "media_center", "importance": 1.0, "topics": ["factcheck"],
                        "text": "FACT CHECK: What's true and what's not in the claims going around today: …"}}]},
    {"id": "rational_priming_30", "label": "Rational priming (30%)", "description": "30% of users are nudged to check facts before reacting (POSIM's RC).",
     "interventions": [{"offset_min": 0, "kind": "node_control", "node_control": {"selector": {"fraction": 0.3}, "action": "prime", "duration_min": 720,
                        "text": "Before reacting, you tend to check the facts, consider other perspectives, and avoid jumping to conclusions."}}]},
    {"id": "rational_priming_100", "label": "Rational priming (100%)", "description": "Everyone is nudged to check facts before reacting.",
     "interventions": [{"offset_min": 0, "kind": "node_control", "node_control": {"selector": {"fraction": 1.0}, "action": "prime", "duration_min": 720,
                        "text": "Before reacting, you tend to check the facts, consider other perspectives, and avoid jumping to conclusions."}}]},
    {"id": "empathy_priming_30", "label": "Empathy priming (30%)", "description": "30% of users are primed to attend to others' feelings (POSIM found this can raise negativity).",
     "interventions": [{"offset_min": 0, "kind": "node_control", "node_control": {"selector": {"fraction": 0.3}, "action": "prime", "duration_min": 720,
                        "text": "You are deeply moved by other people's feelings and pay close attention to how the people around you feel."}}]},
    {"id": "empathy_priming_100", "label": "Empathy priming (100%)", "description": "Everyone is primed toward empathy (the 'empathy paradox' test).",
     "interventions": [{"offset_min": 0, "kind": "node_control", "node_control": {"selector": {"fraction": 1.0}, "action": "prime", "duration_min": 720,
                        "text": "You are deeply moved by other people's feelings and pay close attention to how the people around you feel."}}]},
    {"id": "reduce_virality", "label": "Reduce virality", "description": "The platform down-weights popularity in ranking (w_p 0.3 → 0.1).",
     "interventions": [{"offset_min": 0, "kind": "platform_policy", "platform_policy": {"w_p": 0.1, "w_r": 0.5, "w_h": 0.4}}]},
]


def _officials(cfg: dict) -> list[tuple[str, str]]:
    if cfg.get("candidate_name"):
        out = [("official", f"{cfg['candidate_name'].split(' (')[0]} Campaign")]
        if cfg.get("opponent_name"):
            out.append(("official_opp", f"{cfg['opponent_name'].split(' (')[0]} Campaign"))
        return out
    return [("official", f"{cfg['focal_subject'][:40]} (official)")]


def create_social(body: SocialIn) -> dict:
    store = get_store()
    s = get_settings()
    pop = store.get("populations", body.population_id)
    if not pop:
        raise HTTPException(404, "Population not found")
    ready = store.find("agents", sort="index", fields=["weight"], population_id=body.population_id, persona_status="ready")
    if len(ready) < 10:
        raise HTTPException(422, "Social runs need at least 10 ready agents.")
    n = min(body.n_agents, len(ready), s.sim_max_social_agents)
    seed = body.seed if body.seed is not None else int(new_id()[:7], 16)
    chosen_ids = weighted_sample([a["id"] for a in ready], [a.get("weight") or 1.0 for a in ready], n, rng_for("social", seed))
    agents = [store.get("agents", aid) for aid in chosen_ids]
    agents = [a for a in agents if a]
    cand = store.get("candidates", body.candidate_id) if body.candidate_id else None
    ivs = []
    for i, iv in enumerate([body.seed_event, *body.interventions]):
        d = iv.model_dump()
        d["id"] = d.get("id") or f"iv{i + 1}"
        if i == 0 and not d.get("label"):
            d["label"] = "Seed event"
        ivs.append(d)
    cfg = {
        "agent_ids": [a["id"] for a in agents],
        "focal_subject": body.focal_subject,
        "context": body.context,
        "tick_minutes": body.tick_minutes,
        "duration_hours": body.duration_hours,
        "start_clock": body.start_clock,
        "max_calls_per_tick": body.max_calls_per_tick,
        "checkpoint_every": max(1, round(60 / body.tick_minutes)),
        "interventions": ivs,
        "hawkes": hawkes.params(body.hawkes),
        "feed": feed.params(body.feed),
        "emotion": dynamics.params(body.emotion),
        "seed": seed,
        "geography": pop.get("geography", ""),
        "candidate_name": re.sub(r"\s*\(demo\)\s*$", "", cand["name"]) if cand else "",
        "opponent_name": re.sub(r"\s*\(demo\)\s*$", "", cand.get("opponent_name", "")) if cand else "",
    }
    accounts = network.build(agents, _officials(cfg), seed)
    state = _initial_state(accounts, {a["id"]: a for a in agents}, cfg)
    total = math.ceil(body.duration_hours * 60 / body.tick_minutes)
    est = costs.estimate_social(len(agents), body.duration_hours, body.tick_minutes, body.max_calls_per_tick,
                                costs.persona_tokens(min(600, pop.get("transcript_words") or 600), 3))
    run = new_run("social", body.population_id, body.title, cfg, total, est, candidate_id=body.candidate_id, branch_tick=None)
    state["id"] = run["id"]
    state["run_id"] = run["id"]
    store.insert("sim_state", state)
    return run


def _initial_state(accounts: dict[str, dict], agents: dict[str, dict], cfg: dict) -> dict:
    ag_state = {}
    for aid, acc in accounts.items():
        if acc["role"] == "official":
            continue
        traits = (agents.get(acc["agent_id"]) or {}).get("traits", {}) if acc["agent_id"] else {}
        base = dict(traits.get("baseline_emotion") or {e: 0.05 for e in dynamics.EMOTIONS})
        ag_state[aid] = {
            "emotion": dict(base), "emotion_t": 0.0, "baseline": base, "opinions": [], "memory": [], "seen": [],
            "priming": None, "last_active": -1e9, "stance": 0.0, "muted_until": -1.0, "activations": 0,
            "topics": [t.lower() for t in traits.get("salient_issues", [])],
        }
    return {"clock_tick": 0, "accounts": accounts, "agents": ag_state, "posts": [], "next_post": 1,
            "hawkes": {"exo": [], "endo": []}, "policy": dict(cfg["feed"]), "done_interventions": [], "events": []}


# ---------------------------------------------------------------- one tick


def _clock(cfg: dict, minute: float) -> tuple[str, float]:
    h, m = (int(x) for x in cfg["start_clock"].split(":"))
    offset = h * 60 + m
    total = offset + minute
    day = int(total // 1440)
    label = f"{'Day ' + str(day + 1) + ' ' if day else ''}{int(total % 1440) // 60:02d}:{int(total % 60):02d}"
    return label, float(offset)


def _clean_topics(topics: list[str]) -> list[str]:
    out = []
    for t in topics or []:
        t = re.sub(r"[^\w-]", "", t.strip().lstrip("#")).lower()[:30]
        if t and t not in out:
            out.append(t)
    return out[:3]


def _new_post(state: dict, author: str, kind: str, minute: float, text: str, topics: list[str],
              expr: dict | None, target: dict | None, by_id: dict[str, dict]) -> dict:
    pid = f"p{state['next_post']}"
    state["next_post"] += 1
    stance = 0.0
    emotion, intensity = None, 0.0
    if expr:
        stance = {"support": 1.0, "oppose": -1.0}.get(expr.get("stance", ""), 0.0) * INT.get(expr.get("stance_intensity", "low"), 0.33)
        if expr.get("emotion_type") and expr["emotion_type"] != "neutral":
            emotion, intensity = expr["emotion_type"], INT.get(expr.get("emotion_intensity", "low"), 0.33)
    post = {
        "id": pid, "author": author, "minute": round(minute, 1), "type": kind,
        "parent": target["id"] if target else None,
        "root": (target.get("root") or target["id"]) if target else pid,
        "text": text[: TEXT_LIMIT.get(kind, 1200)], "topics": _clean_topics(topics),
        "emotion": emotion, "intensity": intensity, "stance": round(stance, 2),
        "style": (expr or {}).get("style"), "narrative": (expr or {}).get("narrative"),
        "likes": 0, "reposts": 0, "comments": 0,
    }
    if kind == "repost_with_comment" and target:
        post["quoted_text"] = target.get("text", "")[:240]
        post["root"] = pid  # a quote post starts its own thread but counts toward the original's cascade
        post["cascade_root"] = target.get("cascade_root") or target.get("root") or target["id"]
    state["posts"].append(post)
    by_id[pid] = post
    return post


def _apply_intervention(state: dict, iv: dict, cfg: dict, rng, by_id: dict[str, dict], hp: dict) -> str:
    minute = float(iv["at_minute"])
    label = iv.get("label") or iv["kind"]
    if iv["kind"] == "event" and iv.get("event"):
        ev = iv["event"]
        author = ev.get("author") or "media_center"
        if author not in state["accounts"]:
            author = "official" if author.startswith("official") and "official" in state["accounts"] else "media_center"
        text = str(ev.get("text") or "").strip()
        post = _new_post(state, author, "long_post" if len(text) > 280 else "short_post", minute, text,
                         ev.get("topics") or [], {"stance": "neutral", "emotion_type": "neutral"}, None, by_id)
        post["event"] = True
        importance = float(ev.get("importance") or 1.0)
        state["hawkes"]["exo"].append([minute, hp["alpha_ext"] * max(0.1, min(3.0, importance))])
        state["events"].append({"id": iv["id"], "minute": minute, "text": text[:400], "author": state["accounts"][author]["name"],
                                "post_id": post["id"]})
        return f"{label}: {state['accounts'][author]['name']} posted"
    if iv["kind"] == "node_control" and iv.get("node_control"):
        nc = iv["node_control"]
        sel = nc.get("selector") or {}
        people = [aid for aid, acc in state["accounts"].items() if acc["agent_id"]]
        pool = [aid for aid in people
                if (not sel.get("role") or state["accounts"][aid]["role"] == sel["role"])
                and (not sel.get("party") or state["accounts"][aid].get("party") == sel["party"])]
        frac = float(sel.get("fraction", 1.0))
        chosen = sorted(pool) if frac >= 1 else rng.sample(sorted(pool), max(1, round(frac * len(pool))))
        until = minute + float(nc.get("duration_min") or 720)
        action = nc.get("action", "prime")
        for aid in chosen:
            if action == "prime":
                state["agents"][aid]["priming"] = {"text": str(nc.get("text") or "")[:500], "until": until}
            elif action == "mute":
                state["agents"][aid]["muted_until"] = until
            elif action == "post" and nc.get("text"):
                _new_post(state, aid, "short_post", minute, str(nc["text"]), [], {"stance": "neutral"}, None, by_id)
        return f"{label}: {action} {len(chosen)} accounts"
    if iv["kind"] == "platform_policy" and iv.get("platform_policy"):
        for k, v in iv["platform_policy"].items():
            if k in state["policy"] and v is not None:
                state["policy"][k] = float(v)
        return f"{label}: ranking changed"
    return label


def _tail(state: dict, acct_id: str, cfg: dict, minute: float, feed_text: str, clock: str) -> str:
    ag = state["agents"][acct_id]
    lines = [f"Focal subject: {cfg['focal_subject']}"]
    if cfg.get("context"):
        lines.append(f"<background>\n{cfg['context'][:3000]}\n</background>")
    first_event = min((e["minute"] for e in state["events"]), default=None)
    since = f" — {_ago(minute - first_event)} since the story broke" if first_event is not None and minute >= first_event else ""
    lines.append(f"Time: {clock}{since}.")
    lines.append(f"Your mood right now: {dynamics.describe_mood(ag['emotion'])}.")
    if ag.get("priming") and ag["priming"]["until"] >= minute:
        lines.append(f"About you lately: {ag['priming']['text']}")
    if ag["opinions"]:
        lines.append("Your current views:\n" + "\n".join(
            f"- {o['subject']}: {o['opinion']} (stance {o['stance']:+.1f})" for o in ag["opinions"][-5:]))
    mem = dynamics.recall(ag["memory"], feed_text, set(ag.get("topics", [])), minute)
    if mem:
        lines.append("What you remember:\n" + "\n".join(f"- ({_ago(minute - m['minute'])} ago) {m['text']}" for m in mem))
    trend = feed.trending(state["posts"], minute)
    if trend:
        lines.append("Trending: " + " ".join(trend))
    news = [e for e in state["events"] if 0 <= minute - e["minute"] <= 360]
    if news:
        lines.append("In the news:\n" + "\n".join(f"- {_ago(minute - e['minute'])} ago, {e['author']}: {e['text'][:300]}" for e in news[-3:]))
    lines.append("Your feed:\n" + feed_text)
    lines.append("Now go through perception, belief update, desire and intention. Choose 0-2 actions.")
    return "\n\n".join(lines)


def _ago(minutes: float) -> str:
    minutes = max(0, int(minutes))
    return f"{minutes}m" if minutes < 90 else f"{minutes // 60}h{minutes % 60:02d}m"


def run_tick(ctx: StepCtx, state: dict, cfg: dict, agent_docs: dict[str, dict]) -> dict:
    s = get_settings()
    store = get_store()
    rid = ctx.run["id"]
    k = state["clock_tick"]
    dt = cfg["tick_minutes"]
    t0, tmid = k * dt, k * dt + dt / 2
    rng = rng_for("tick", cfg["seed"], k)
    hp = cfg["hawkes"]
    ep = cfg["emotion"]
    people = [aid for aid, acc in state["accounts"].items() if acc["agent_id"]]
    M = len(people)
    by_id = {p["id"]: p for p in state["posts"]}

    if k % cfg["checkpoint_every"] == 0:
        store.upsert_many("sim_checkpoints", [{"id": f"{rid}:{k}", "run_id": rid, "tick": k, "state": copy.deepcopy(state)}])

    applied = []
    for iv in cfg["interventions"]:
        if iv["id"] in state["done_interventions"] or not (iv["at_minute"] < t0 + dt):
            continue
        applied.append(_apply_intervention(state, iv, cfg, rng, by_id, hp))
        state["done_interventions"].append(iv["id"])

    clock, offset = _clock(cfg, tmid)
    lam = hawkes.intensity(tmid, offset, hp, M, state["hawkes"]["exo"], state["hawkes"]["endo"])
    demand = poisson(hawkes.expected_activations(lam, M, dt), rng)
    remaining = ctx.run["budget"]["max_calls"] - ctx.run["progress"].get("calls", 0) - ctx.calls
    served = max(0, min(demand, int(cfg["max_calls_per_tick"]), remaining))
    if demand and remaining <= 0:
        ctx.status = "budget_exhausted"
    recent = state["posts"][-300:]
    cands = []
    for aid, ag in state["agents"].items():
        acc = state["accounts"][aid]
        if ag.get("muted_until", -1) >= t0:
            continue
        follows = set(acc["follows"])
        seen = set(ag["seen"][-200:])
        unseen = sum(1 for p in recent if p["author"] in follows and p["id"] not in seen)
        w = acc["activity"] * (1 + 0.5 * min(1.0, unseen / 5)) * (0.3 if t0 - ag["last_active"] < 30 else 1.0)
        cands.append((aid, w))
    active = hawkes.pick_active(cands, served, rng)

    items = []
    feeds: dict[str, tuple[list[dict], dict[str, list[dict]]]] = {}
    pol = feed.params(state["policy"])
    for aid in active:
        f_posts, f_comments = feed.build(state, aid, tmid, pol, rng)
        feeds[aid] = (f_posts, f_comments)
        ag = state["agents"][aid]
        ag["emotion"] = dynamics.decay(ag["emotion"], ag["baseline"], tmid - ag["emotion_t"], ep["half_life_min"])
        ag["emotion_t"] = tmid
        acc = state["accounts"][aid]
        persona = SP.social_persona_block(agent_docs.get(acc["agent_id"]) if acc["agent_id"] else None, acc, cfg.get("geography", ""))
        tail = _tail(state, aid, cfg, tmid, feed.render(f_posts, f_comments, state["accounts"], tmid), clock)
        items.append((aid, persona, tail))

    def call(item: tuple[str, str, str]) -> tuple[SocialActivation, dict]:
        _, persona, tail = item
        return llm.structured(
            tail, SocialActivation, system=SP.SOCIAL_SYSTEM, cache_system=True, blocks=[llm.Block(persona, cache=True)],
            effort=s.sim_agent_effort, thinking=s.sim_agent_thinking,  # type: ignore[arg-type]
            model=s.sim_model, max_tokens=3000, timeout=s.sim_call_timeout, max_retries=1, log_level=logging.DEBUG,
        )

    results = ctx.parallel(call, items) if items else []
    counts = {t: 0 for t in ("like", "repost", "repost_with_comment", "short_comment", "long_comment", "short_post", "long_post")}
    created: list[dict] = []
    failures = 0
    for (aid, _, _), out, err in results:
        ag = state["agents"][aid]
        acc = state["accounts"][aid]
        ag["last_active"] = tmid
        ag["activations"] = ag.get("activations", 0) + 1
        if err is not None or out is None:
            failures += 1
            continue
        f_posts, f_comments = feeds[aid]
        shown = {p["id"]: p for p in f_posts} | {c["id"]: c for cs in f_comments.values() for c in cs}
        ag["emotion"] = dynamics.stimulate(ag["emotion"], out.belief.emotions.model_dump(), ep["eta"])
        ag["opinions"] = dynamics.upsert_opinions(ag["opinions"], [o.model_dump() for o in out.belief.opinions[:3]], tmid)
        ag["stance"] = dynamics.focal_stance(ag["opinions"], cfg["focal_subject"], ag.get("stance", 0.0))
        for o in out.belief.opinions[:1]:
            ag["memory"] = dynamics.remember(ag["memory"], {"minute": tmid, "importance": 0.9, "topics": [],
                                                            "text": f"You concluded about {o.subject}: {o.opinion}"})
        new_posts = 0
        for action in out.actions[:2]:
            a = action.model_dump()
            kind = a["action_type"]
            target = shown.get((a.get("target_id") or "").strip().strip("[]"))
            if kind in ("like", "repost", "repost_with_comment", "short_comment", "long_comment") and target is None:
                continue
            text = (a.get("content") or {}).get("text", "").strip()
            topics = (a.get("content") or {}).get("topics", [])
            if kind == "like":
                target["likes"] = target.get("likes", 0) + 1
                state["hawkes"]["endo"].append([tmid, 0.2])
            elif kind == "repost":
                root = by_id.get(target.get("root") or target["id"], target)
                root["reposts"] = root.get("reposts", 0) + 1
                _new_post(state, aid, "repost", tmid, "", [], a.get("expression"), root, by_id)
                state["hawkes"]["endo"].append([tmid, 1.0])
            else:
                if not text or (kind in ("short_post", "long_post") and new_posts >= 1):
                    continue
                if kind in ("short_post", "long_post"):
                    target = None
                    new_posts += 1
                if kind in ("short_comment", "long_comment"):
                    target["comments"] = target.get("comments", 0) + 1
                    root = by_id.get(target.get("root") or "")
                    if root is not None and root is not target:
                        root["comments"] = root.get("comments", 0) + 1
                if kind == "repost_with_comment":
                    target["reposts"] = target.get("reposts", 0) + 1
                post = _new_post(state, aid, kind, tmid, text, topics, a.get("expression"), target, by_id)
                created.append(post)
                state["hawkes"]["endo"].append([tmid, 1.0])
                verb = {"short_post": "posted", "long_post": "posted", "repost_with_comment": "quote-reposted",
                        "short_comment": "commented", "long_comment": "commented"}[kind]
                ag["memory"] = dynamics.remember(ag["memory"], {"minute": tmid, "importance": 0.8, "topics": post["topics"],
                                                                "text": f"You {verb}: {text[:200]}"})
            counts[kind] += 1
        if f_posts:
            weighted = [(p, 1.0 / (i + 1)) for i, p in enumerate(f_posts)]
            ag["emotion"] = dynamics.contagion(ag["emotion"], weighted, ep["rho"])
            best = f_posts[0]
            ag["memory"] = dynamics.remember(ag["memory"], {
                "minute": tmid, "importance": 1.0 if best.get("event") else 0.4, "topics": best.get("topics", []),
                "text": f"You saw @{state['accounts'][best['author']]['name']}: {best['text'][:200]}"})
        ag["topics"] = list(dict.fromkeys(ag.get("topics", []) + [t for p in f_posts[:3] for t in p.get("topics", [])]))[-8:]
        if acc["role"] == "media":
            ag["stance"] = 0.0

    state["hawkes"]["exo"] = hawkes.prune(state["hawkes"]["exo"], tmid, hp["beta_ext"], 1.0)
    state["hawkes"]["endo"] = hawkes.prune(state["hawkes"]["endo"], tmid, hp["beta_int"], hawkes.endo_jump(hp, M))
    state["clock_tick"] = k + 1

    # tick metrics
    emo_counts = {e: 0.0 for e in dynamics.EMOTIONS}
    vals = []
    for p in created:
        if p.get("emotion"):
            emo_counts[p["emotion"]] += 1
        vals.append(metrics.valence(p.get("emotion"), p.get("intensity", 0.0)))
    emotional = sum(emo_counts.values())
    stances = [state["agents"][a]["stance"] for a in people if state["agents"][a]["opinions"]]
    by_party: dict[str, list[float]] = {}
    for a in people:
        if state["agents"][a]["opinions"]:
            by_party.setdefault(state["accounts"][a].get("party") or "unknown", []).append(state["agents"][a]["stance"])
    mood = {e: round(sum(state["agents"][a]["emotion"][e] for a in people) / max(1, M), 3) for e in dynamics.EMOTIONS}
    row = {
        "id": f"{rid}:{k}", "run_id": rid, "tick": k, "minute": t0, "clock": _clock(cfg, t0)[0],
        "lambda": round(lam, 5), "demand": demand, "served": len(active), "failed": failures,
        "actions": counts, "content": len(created),
        "sentiment": metrics.r(sum(vals) / len(vals), 3) if vals else None,
        "neg": sum(emo_counts[e] for e in NEGATIVE), "emotional": emotional,
        "ner": metrics.r(sum(emo_counts[e] for e in NEGATIVE) / emotional, 3) if emotional else None,
        "pi": metrics.r(metrics.emotional_concentration(emo_counts), 3),
        "stance_mean": metrics.r(sum(stances) / len(stances), 3) if stances else None,
        "stance_by_party": {pty: metrics.r(sum(v) / len(v), 3) for pty, v in by_party.items()},
        "sp": metrics.r(metrics.stance_polarization(stances), 3),
        "with_opinion": len(stances),
        "mood": mood,
        "events": applied,
    }
    ctx.failed += failures
    ctx.done += len(active) - failures
    return row


def step(ctx: StepCtx) -> None:
    store = get_store()
    run = ctx.run
    cfg = run["config"]
    state = store.get("sim_state", run["id"])
    if not state:
        raise HTTPException(409, "This run's state is missing.")
    agent_docs = {a["id"]: a for a in (store.get("agents", aid) for aid in cfg["agent_ids"]) if a}
    total = run["total"]
    import time

    while state["clock_tick"] < total and ctx.should_continue():
        if ctx.batch_times and ctx.canceled():
            break
        if not ctx.budget_ok(1):
            ctx.status = "budget_exhausted"
            ctx.note("Stopped at the call budget. Raise it to continue.")
            break
        t = time.monotonic()
        row = run_tick(ctx, state, cfg, agent_docs)
        store.upsert_many("sim_state", [state])
        store.upsert_many("sim_ticks", [row])
        if row["served"] or ctx.batch_times:
            ctx.batch_times.append(time.monotonic() - t)
        if row["events"]:
            ctx.note(f"{row['clock']}: " + "; ".join(row["events"]))
        if ctx.status == "budget_exhausted":
            break
    ctx.cursor = state["clock_tick"]
    if state["clock_tick"] >= total and ctx.status is None and ctx.fatal is None:
        ctx.status = "finalizing"


def _cascade_sizes(posts: list[dict]) -> dict[str, int]:
    roots = {p["id"]: 1 for p in posts if p["type"] in ("short_post", "long_post", "repost_with_comment")}
    for p in posts:
        root = p.get("cascade_root") if p["type"] == "repost_with_comment" else (p.get("root") if p["id"] != p.get("root") else None)
        if root in roots:
            roots[root] += 1
    return roots


def finalize(ctx: StepCtx) -> None:
    store = get_store()
    run = ctx.run
    state = store.get("sim_state", run["id"]) or {}
    posts = state.get("posts", [])
    accounts = state.get("accounts", {})
    ticks = ticks_for(run)
    sizes = _cascade_sizes(posts)
    content = [p for p in posts if p["type"] in CONTENT_TYPES and not p.get("event")]
    emo = {e: 0.0 for e in dynamics.EMOTIONS}
    for p in content:
        if p.get("emotion"):
            emo[p["emotion"]] += 1
    emotional = sum(emo.values())
    vals = [metrics.valence(p.get("emotion"), p.get("intensity", 0)) for p in content]
    top = sorted((p for p in posts if p["type"] in ("short_post", "long_post", "repost_with_comment")),
                 key=lambda p: -(feed.engagement(p) + sizes.get(p["id"], 1)))[:10]
    people = [a for a, acc in accounts.items() if acc.get("agent_id")]
    by_party: dict[str, list[float]] = {}
    for a in people:
        ag = state["agents"][a]
        if ag["opinions"]:
            by_party.setdefault(accounts[a].get("party") or "unknown", []).append(ag["stance"])
    peak = max(ticks, key=lambda t: t.get("served", 0), default=None)
    ctx.patch["results"] = {
        "activations": sum(t.get("served", 0) for t in ticks),
        "demand": sum(t.get("demand", 0) for t in ticks),
        "posts": sum(1 for p in content if p["type"] in ("short_post", "long_post")),
        "comments": sum(1 for p in content if "comment" in p["type"]),
        "reposts": sum(1 for p in posts if p["type"] in ("repost", "repost_with_comment")),
        "likes": sum(p.get("likes", 0) for p in posts),
        "ner": metrics.r(sum(emo[e] for e in NEGATIVE) / emotional, 3) if emotional else None,
        "sentiment": metrics.r(sum(vals) / len(vals), 3) if vals else None,
        "pi": metrics.r(metrics.emotional_concentration(emo), 3),
        "emotions": emo,
        "stance_by_party": {k: metrics.r(sum(v) / len(v), 3) for k, v in by_party.items()},
        "with_opinion": sum(len(v) for v in by_party.values()),
        "cascades": metrics.cascade_histogram(list(sizes.values())),
        "max_cascade": max(sizes.values(), default=0),
        "peak": {"clock": peak.get("clock"), "served": peak.get("served")} if peak else None,
        "top_posts": [_post_out(p, accounts, sizes) for p in top],
    }
    ctx.status = "done"


def _post_out(p: dict, accounts: dict[str, dict], sizes: dict[str, int] | None = None) -> dict:
    acc = accounts.get(p["author"], {})
    out = {k: p.get(k) for k in ("id", "type", "minute", "text", "topics", "emotion", "intensity", "stance", "style",
                                  "narrative", "likes", "reposts", "comments", "parent", "root", "event", "quoted_text")}
    out["author"] = {"id": p["author"], "name": acc.get("name", "?"), "role": acc.get("role"), "party": acc.get("party")}
    if sizes is not None:
        out["cascade"] = sizes.get(p["id"])
    return out


# ---------------------------------------------------------------- views, branching, comparison


def _lineage(run: dict) -> list[tuple[dict, int | None]]:
    """[(ancestor run, last tick to take from it)] oldest first, ending with this run."""
    store = get_store()
    chain: list[tuple[dict, int | None]] = [(run, None)]
    cur = run
    while cur.get("parent_run_id"):
        parent = store.get("sim_runs", cur["parent_run_id"])
        if not parent:
            break
        chain.insert(0, (parent, cur.get("branch_tick")))
        cur = parent
    return chain


def ticks_for(run: dict) -> list[dict]:
    store = get_store()
    out: list[dict] = []
    chain = _lineage(run)
    for i, (r, _) in enumerate(chain):
        upto = chain[i + 1][0].get("branch_tick") if i + 1 < len(chain) else None
        rows = sorted(store.find("sim_ticks", run_id=r["id"]), key=lambda t: t["tick"])
        start = out[-1]["tick"] + 1 if out else 0
        out += [t for t in rows if t["tick"] >= start and (upto is None or t["tick"] < upto)]
    return out


def posts_view(run: dict, root: str | None = None, author: str | None = None, limit: int = 200) -> dict:
    state = get_store().get("sim_state", run["id"]) or {}
    posts = state.get("posts", [])
    accounts = state.get("accounts", {})
    sizes = _cascade_sizes(posts)
    if root:
        thread = [p for p in posts if p["id"] == root or p.get("root") == root or p.get("cascade_root") == root]
        return {"posts": [_post_out(p, accounts, sizes) for p in sorted(thread, key=lambda p: p["minute"])]}
    sel = [p for p in posts if p["type"] != "repost" and (not author or p["author"] == author)]
    sel.sort(key=lambda p: -p["minute"])
    return {"total": len(sel), "posts": [_post_out(p, accounts, sizes) for p in sel[:limit]]}


def network_view(run: dict) -> dict:
    state = get_store().get("sim_state", run["id"]) or {}
    accounts = state.get("accounts", {})
    out = network.summary(accounts) if accounts else {}
    agents = state.get("agents", {})
    out["most_active"] = sorted(
        ({"id": a, "name": accounts[a]["name"], "role": accounts[a]["role"], "party": accounts[a].get("party"),
          "activations": ag.get("activations", 0), "stance": round(ag.get("stance", 0.0), 2)}
         for a, ag in agents.items()), key=lambda x: -x["activations"])[:12]
    return out


def branch(run: dict, body: BranchIn) -> list[dict]:
    store = get_store()
    if run["kind"] != "social":
        raise HTTPException(409, "Only social runs can branch.")
    cps: list[dict] = []
    for r, upto in _lineage(run):
        for cp in store.find("sim_checkpoints", fields=["tick", "run_id"], run_id=r["id"]):
            if upto is None or cp["tick"] <= upto:
                cps.append(cp)
    cps = [cp for cp in cps if cp["tick"] <= body.tick]
    if not cps:
        raise HTTPException(422, "No checkpoint at or before that tick yet.")
    cp_ref = max(cps, key=lambda c: (c["tick"], c["run_id"] == run["id"]))
    cp = store.get("sim_checkpoints", cp_ref["id"]) or {}
    tick = cp_ref["tick"]
    cfg = run["config"]
    branch_min = tick * cfg["tick_minutes"]
    new_ivs = []
    for i, iv in enumerate(body.interventions):
        d = iv.model_dump()
        d["id"] = f"b{tick}_{i + 1}_{new_id()[:4]}"
        d["at_minute"] = max(branch_min, d["at_minute"])
        new_ivs.append(d)
    remaining = run["total"] - tick
    est = costs.estimate_social(len(cfg["agent_ids"]), max(1, math.ceil(remaining * cfg["tick_minutes"] / 60)),
                                cfg["tick_minutes"], cfg["max_calls_per_tick"])
    title = body.title or ("Branch: " + ", ".join(iv.get("label") or iv["kind"] for iv in new_ivs) if new_ivs else "Branch")
    variants = [(title, cfg["interventions"] + new_ivs)]
    if body.with_control:
        variants.append((f"Control from {_clock(cfg, branch_min)[0]} (no change)", cfg["interventions"]))
    out = []
    for t, ivs in variants:
        new = new_run("social", run["population_id"], t, cfg | {"interventions": ivs}, run["total"], est,
                      candidate_id=run.get("candidate_id"), parent_run_id=run["id"], branch_tick=tick)
        new = store.update("sim_runs", new["id"], {"cursor": tick}) or new
        state = copy.deepcopy(cp["state"])
        state["id"] = new["id"]
        state["run_id"] = new["id"]
        store.insert("sim_state", state)
        out.append(new)
    return out


def compare(run: dict, others: list[dict]) -> dict:
    runs = [run, *others]
    series = []
    start = max((r.get("branch_tick") or 0) for r in runs)
    for r in runs:
        ticks = ticks_for(r)
        after = [t for t in ticks if t["tick"] >= start]
        neg = sum(t.get("neg", 0) for t in after)
        emotional = sum(t.get("emotional", 0) for t in after)
        sents = [t["sentiment"] for t in after if t.get("sentiment") is not None]
        last_stance = next((t["stance_mean"] for t in reversed(after) if t.get("stance_mean") is not None), None)
        series.append({
            "run_id": r["id"], "title": r["title"], "status": r["status"],
            "ticks": [{k: t.get(k) for k in ("tick", "clock", "served", "ner", "sentiment", "stance_mean", "sp", "content")} for t in ticks],
            "summary": {"ner": metrics.r(neg / emotional, 3) if emotional else None,
                        "sentiment": metrics.r(sum(sents) / len(sents), 3) if sents else None,
                        "final_stance": last_stance, "content": sum(t.get("content", 0) for t in after),
                        "activations": sum(t.get("served", 0) for t in after)},
        })
    base = series[-1]["summary"] if len(series) > 1 else series[0]["summary"]
    for s_ in series:
        s_["delta_vs_last"] = {k: metrics.r(s_["summary"][k] - base[k], 3) if s_["summary"].get(k) is not None and base.get(k) is not None else None
                               for k in ("ner", "sentiment", "final_stance")}
    return {"from_tick": start, "runs": series}


def failed_units(run: dict) -> list[int]:
    return []


def template_interventions(template_id: str, start_minute: int) -> list[Intervention]:
    tpl = next((t for t in TEMPLATES if t["id"] == template_id), None)
    if not tpl:
        return []
    out = []
    for iv in tpl["interventions"]:
        d: dict[str, Any] = {k: v for k, v in iv.items() if k != "offset_min"}
        d["at_minute"] = start_minute + iv["offset_min"]
        d["label"] = tpl["label"]
        out.append(Intervention(**d))
    return out
