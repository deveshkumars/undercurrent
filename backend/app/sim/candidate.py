"""Candidate hooks: race context, poll-segment mapping, calibration against real polls, and backtests
against past events with measured impact.

Calibration compares the simulated vote split under a no-message control with the candidate's
house-adjusted polling average per segment, and can rake a second weight set to match it.
Backtests replay past events as stimuli (with context as of the day before) and fit
measured ≈ β × simulated through the origin; later panel effects can be shown as β × effect.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any, Callable

from fastapi import HTTPException

from .. import analytics
from ..models import utcnow
from ..storage import get_store
from . import costs, metrics
from . import demographics as D
from . import presets as P
from .models import Arm, BacktestIn, CalibrationIn, PanelIn, Question
from .panel import _ready_agents, _sample, agent_call, create_panel, response_doc
from .runner import StepCtx, batch_loop, new_run
from .schemas import make_panel_schema

Predicate = Callable[[dict], "bool | None"]
BAND_MID = {"18-29": 24, "30-44": 37, "45-64": 55, "65+": 72}


def display_name(name: str) -> str:
    """Drop the demo marker so agents read a plain name."""
    return re.sub(r"\s*\(demo\)\s*$", "", name or "").strip()


def _candidate(cid: str) -> dict:
    cand = get_store().get("candidates", cid)
    if not cand:
        raise HTTPException(404, "Candidate not found")
    return cand


# ---------------------------------------------------------------- context


def race_context(cand: dict, as_of: date | None = None, max_events: int = 6) -> str:
    """What an ordinary voter could plausibly know about the race, as of a date. No poll numbers:
    those would anchor the agents and contaminate calibration."""
    lines = []
    name = display_name(cand["name"])
    office = f" for {cand['office']}" if cand.get("office") else ""
    where = f" in {cand['jurisdiction']}" if cand.get("jurisdiction") else ""
    party = f" ({cand['party']})" if cand.get("party") else ""
    lines.append(f"{name}{party} is running{office}{where}.")
    if cand.get("opponent_name"):
        lines.append(f"The main opponent is {display_name(cand['opponent_name'])}.")
    if cand.get("election_date"):
        lines.append(f"Election day is {cand['election_date']}.")
    if cand.get("bio"):
        bio = re.sub(r"\s*(Fictional demo candidate\.|All data is synthetic\.)\s*", " ", cand["bio"]).strip()
        if bio:
            lines.append(f"About {name}: {bio[:600]}")
    events = sorted(get_store().find("events", candidate_id=cand["id"]), key=lambda e: str(e["date"]))
    if as_of:
        events = [e for e in events if str(e["date"]) <= as_of.isoformat()]
    recent = events[-max_events:]
    if recent:
        lines.append("")
        lines.append("Things that have been in the news recently:")
        for e in recent:
            summary = (e.get("summary") or "").strip()
            lines.append(f"- {e['date']}: {e['title']}" + (f". {summary[:300]}" if summary else ""))
    if as_of:
        lines.append("")
        lines.append(f"Today is {as_of.isoformat()}.")
    return "\n".join(lines)


# ---------------------------------------------------------------- poll segments


def _age_of(demo: dict) -> int | None:
    if demo.get("age") is not None:
        return int(demo["age"])
    return BAND_MID.get(demo.get("age_band") or "")


def _eq(field: str, *values: str) -> Predicate:
    def f(demo: dict) -> bool | None:
        v = demo.get(field)
        return None if v is None else v in values
    return f


def _age_pred(lo: int | None, hi: int | None) -> Predicate:
    def f(demo: dict) -> bool | None:
        a = _age_of(demo)
        if a is None:
            return None
        return (lo is None or a >= lo) and (hi is None or a <= hi)
    return f


def parse_segment(label: str) -> Predicate | None:
    """'Independents', 'Women', 'Under 35', 'Hispanic women', 'College grads 65+' -> predicate; None if unknown."""
    text = label.lower().replace("–", "-").strip()
    preds: list[Predicate] = []
    m = re.search(r"under\s*(\d{2})", text)
    if m:
        preds.append(_age_pred(None, int(m.group(1)) - 1))
        text = text.replace(m.group(0), " ")
    m = re.search(r"(\d{2})\s*-\s*(\d{2})", text)
    if m:
        preds.append(_age_pred(int(m.group(1)), int(m.group(2))))
        text = text.replace(m.group(0), " ")
    m = re.search(r"(\d{2})\s*(\+|and over|and older|or older)|over\s*(\d{2})", text)
    if m:
        preds.append(_age_pred(int(m.group(1) or m.group(3)), None))
        text = text.replace(m.group(0), " ")
    vocab: list[tuple[str, Predicate]] = [
        (r"non-?college|no degree|without a degree|non-graduates?", _eq("education", "hs_or_less", "some_college")),
        (r"college (grads?|graduates?|educated)|with a degree|degree holders", _eq("education", "bachelors", "postgrad")),
        (r"independents?|unaffiliated", _eq("party", "independent")),
        (r"democrats?|democratic|dems?\b", _eq("party", "democrat")),
        (r"republicans?|gop", _eq("party", "republican")),
        (r"women|female", _eq("gender", "female")),
        (r"\bmen\b|\bmale\b", _eq("gender", "male")),
        (r"hispanics?|latino|latina|latinx", _eq("race", "hispanic")),
        (r"black|african.american", _eq("race", "black")),
        (r"white", _eq("race", "white")),
        (r"asian", _eq("race", "asian")),
        (r"suburban|suburbs", _eq("urbanicity", "suburban")),
        (r"urban|city", _eq("urbanicity", "urban")),
        (r"rural", _eq("urbanicity", "rural")),
        (r"liberals?", _eq("ideology", "liberal")),
        (r"moderates?", _eq("ideology", "moderate")),
        (r"conservatives?", _eq("ideology", "conservative")),
        (r"seniors?|retirees?", _age_pred(65, None)),
        (r"young (voters|people|adults)", _age_pred(18, 29)),
    ]
    for pattern, pred in vocab:
        m2 = re.search(pattern, text)
        if m2:
            preds.append(pred)
            text = text[: m2.start()] + " " + text[m2.end():]
    leftover = re.sub(r"\b(and|&|voters?|people|adults|ages?|aged|all|the|of|incl\.?|including|leaners)\b|[,/()]", " ", text).strip()
    if not preds or leftover:
        return None

    def combined(demo: dict) -> bool | None:
        vals = [p(demo) for p in preds]
        if any(v is False for v in vals):
            return False
        if any(v is None for v in vals):
            return None
        return True
    return combined


def poll_segments(cid: str) -> list[str]:
    labels = {p.get("segment") or "All" for p in get_store().find("polls", fields=["segment"], candidate_id=cid)}
    return sorted(labels - {"All"})


def poll_segment_predicates(cid: str, unmapped: list[str] | None = None) -> dict[str, Predicate]:
    out = {}
    for label in poll_segments(cid):
        pred = parse_segment(label)
        if pred is None:
            if unmapped is not None:
                unmapped.append(label)
            continue
        out[label] = pred
    return out


def segment_mapping(cid: str, pid: str) -> dict[str, Any]:
    """Which poll segments map onto agents, and each segment's share of the population."""
    agents = _ready_agents(pid) or get_store().find("agents", fields=["demographics", "weight"], population_id=pid)
    unmapped: list[str] = []
    preds = poll_segment_predicates(cid, unmapped)
    rows = []
    W = sum(a.get("weight", 1.0) for a in agents) or 1.0
    for label, pred in preds.items():
        members = [a for a in agents if pred(a.get("demographics", {}))]
        rows.append({"segment": label, "agents": len(members),
                     "weighted_share": round(sum(a.get("weight", 1.0) for a in members) / W, 4)})
    return {"segments": rows, "unmapped": unmapped, "suggested_targets": suggested_targets(cid)}


def suggested_targets(cid: str) -> dict[str, float]:
    """Each crosstab's typical share of the full sample (median n_seg / n_all over same-day, same-pollster polls)."""
    polls = get_store().find("polls", fields=["date", "pollster", "segment", "sample_size", "metric"], candidate_id=cid)
    alls = {(str(p["date"]), p.get("pollster"), p.get("metric")): p.get("sample_size") for p in polls if (p.get("segment") or "All") == "All"}
    ratios: dict[str, list[float]] = {}
    for p in polls:
        seg = p.get("segment") or "All"
        if seg == "All":
            continue
        n_all = alls.get((str(p["date"]), p.get("pollster"), p.get("metric")))
        if n_all and p.get("sample_size"):
            ratios.setdefault(seg, []).append(p["sample_size"] / n_all)
    return {seg: round(sorted(v)[len(v) // 2], 3) for seg, v in ratios.items() if v}


# ---------------------------------------------------------------- calibration


def create_calibration(cid: str, body: CalibrationIn) -> dict:
    cand = _candidate(cid)
    pop = get_store().get("populations", body.population_id)
    if not pop:
        raise HTTPException(404, "Population not found")
    questions = [q for q in P.questionnaire("political", display_name(cand["name"]), display_name(cand.get("opponent_name", "")))
                 if q["id"] in ("vote_choice", "thermometer", "turnout")]
    context = body.context if body.context is not None else race_context(cand, date.today())
    # a control-only panel (PanelIn's validator insists on treatments, so build it unvalidated)
    panel = PanelIn.model_construct(
        population_id=body.population_id,
        candidate_id=cid,
        title=f"Calibration: {cand['name']}",
        subject="",
        opponent="",
        context=context,
        arms=[Arm(id="control", label="No message", kind="control", control_mode="none")],
        questionnaire="custom",
        questions=[Question(**q) for q in questions],
        sample_size=body.sample_size,
        replicates=1,
        weight_set="demographic",
        likely_voter=False,
        seed=None,
        source_report_id=None,
    )
    return create_panel(panel, kind="calibration")


def _vote_bucket(choice_fracs: dict[str, float] | None, options: list[str]) -> str | None:
    """Collapse replicate answers to the modal bucket: cand / opp / undec, or None for non-voters."""
    if not choice_fracs:
        return None
    top = max(choice_fracs.items(), key=lambda kv: kv[1])[0]
    if top == options[0]:
        return "cand"
    if top == options[1]:
        return "opp"
    if top == "wouldn't vote":
        return None
    return "undec"


def _sim_split(records: list[dict], members: set[str] | None, q: dict, control: str) -> dict[str, Any]:
    tot = {"cand": 0.0, "opp": 0.0, "undec": 0.0}
    ws: list[float] = []
    xs: list[float] = []
    for rec in records:
        if members is not None and rec["id"] not in members:
            continue
        fr = rec["cat"].get(control, {}).get(q["id"])
        if not fr:
            continue
        voting = 1.0 - fr.get("wouldn't vote", 0.0)
        if voting <= 0:
            continue
        cand = fr.get(q["options"][0], 0.0) / voting
        opp = fr.get(q["options"][1], 0.0) / voting
        w = rec["w"] * voting
        tot["cand"] += w * cand
        tot["opp"] += w * opp
        tot["undec"] += w * (1 - cand - opp)
        ws.append(w)
        xs.append(100 * cand)
    W = sum(ws)
    if W <= 0:
        return {"n": 0}
    lin = metrics.linearized(xs, ws)
    return {"cand": round(100 * tot["cand"] / W, 1), "opp": round(100 * tot["opp"] / W, 1),
            "undec": round(100 * tot["undec"] / W, 1), "se": metrics.r(lin["se"], 2), "n": len(ws),
            "n_eff": round(metrics.n_eff(ws), 1)}


def _poll_target(cid: str, segment: str) -> dict | None:
    store = get_store()
    res = analytics.analyze(store.find("polls", candidate_id=cid), store.find("events", candidate_id=cid), "vote_share", segment)
    st = res["stats"]
    if res["metric"] != "vote_share" or not st.get("poll_count") or st.get("latest") is None:
        return None
    opp = st.get("opponent_latest")
    return {"cand": metrics.r(st["latest"], 1), "opp": metrics.r(opp, 1),
            "undec": metrics.r(100 - st["latest"] - (opp or 0), 1) if opp is not None else None,
            "se": metrics.r(st.get("latest_se"), 2), "as_of": st.get("latest_date"), "polls": st.get("poll_count")}


def calibration_table(run: dict, weight_key: str = "weight") -> tuple[list[dict], list[dict], dict]:
    store = get_store()
    cfg = run["config"]
    q = next(q for q in cfg["questions"] if q["id"] == "vote_choice")
    control = cfg["arms"][0]["id"]
    agents = {a["id"]: a for a in store.find("agents", fields=["demographics", "weight", "weight_cal"],
                                             population_id=run["population_id"]) if a["id"] in set(cfg["agent_ids"])}
    responses = store.find("sim_results", run_id=run["id"])
    records = metrics.agent_records(responses, agents, cfg["questions"], weight_key, False, control)
    cid = run["candidate_id"]
    preds = {"All": None, **poll_segment_predicates(cid)}
    rows = []
    for label, pred in preds.items():
        members = None if pred is None else {aid for aid, a in agents.items() if pred(a.get("demographics", {}))}
        sim = _sim_split(records, members, q, control)
        poll = _poll_target(cid, label)
        row: dict[str, Any] = {"segment": label, "sim": sim, "poll": poll}
        if poll and sim.get("n"):
            diff = sim["cand"] - poll["cand"]
            se = math.sqrt((poll.get("se") or 0) ** 2 + (sim.get("se") or 0) ** 2) or None
            row["diff"] = round(diff, 1)
            row["z"] = round(diff / se, 2) if se else None
            if poll.get("opp") is not None:
                row["diff_opp"] = round(sim["opp"] - poll["opp"], 1)
        rows.append(row)
    return rows, records, agents


def _grade(mae: float | None) -> str:
    if mae is None:
        return "n/a"
    return "good" if mae < 3 else "fair" if mae < 6 else "poor"


def finalize_calibration(ctx: StepCtx) -> None:
    run = ctx.run
    rows, records, _ = calibration_table(run)
    diffs = [abs(r["diff"]) for r in rows if r.get("diff") is not None]
    mae = round(sum(diffs) / len(diffs), 2) if diffs else None
    res = {"segments": rows, "mae": mae, "grade": _grade(mae), "n_agents": len(records), "applied": False}
    ctx.patch["results"] = res
    get_store().update("populations", run["population_id"], {"calibration": {
        "candidate_id": run["candidate_id"], "run_id": run["id"], "mae": mae, "grade": _grade(mae), "at": utcnow(),
        "applied": False,
    }})
    ctx.note(f"Calibration MAE {mae} pp ({_grade(mae)})" if mae is not None else "No polls to compare against.")
    ctx.status = "done"


def apply_calibration(run: dict) -> dict:
    """Rake weight_cal so the simulated vote split matches the polls in every mapped segment."""
    store = get_store()
    if run["kind"] != "calibration" or run["status"] != "done":
        raise HTTPException(409, "Apply works on a finished calibration run.")
    pop = store.get("populations", run["population_id"]) or {}
    rows_before, records, agents = calibration_table(run)
    cfg = run["config"]
    q = next(q for q in cfg["questions"] if q["id"] == "vote_choice")
    control = cfg["arms"][0]["id"]
    rec_by_id = {r["id"]: r for r in records}
    ids = [aid for aid in cfg["agent_ids"] if aid in rec_by_id and aid in agents]
    rake_rows: list[dict] = []
    base: list[float] = []
    for aid in ids:
        row = dict(agents[aid].get("demographics", {}))
        row["vote_cal"] = _vote_bucket(rec_by_id[aid]["cat"].get(control, {}).get(q["id"]), q["options"])
        rake_rows.append(row)
        base.append(agents[aid].get("weight") or 1.0)
    margins = {k: v for k, v in D.effective_margins(pop.get("preset") or "us_registered_voters", pop.get("targets") or {}).items()
               if any(r.get(k) is not None for r in rake_rows)} if pop.get("source") != "csv" else {}
    W = sum(base) or 1.0
    applied_segments = []
    for row in rows_before:
        poll = row.get("poll")
        if not poll or poll.get("opp") is None:
            continue
        split = {"cand": poll["cand"], "opp": poll["opp"], "undec": max(0.0, 100 - poll["cand"] - poll["opp"])}
        tot = sum(split.values()) or 100.0
        if row["segment"] == "All":
            margins["vote_cal"] = {k: v / tot for k, v in split.items()}
            applied_segments.append("All")
            continue
        pred = parse_segment(row["segment"])
        if pred is None:
            continue
        key = f"seg_{len(applied_segments)}"
        member_w = 0.0
        for r_, aid, b in zip(rake_rows, ids, base):
            hit = pred(agents[aid].get("demographics", {}))
            if hit is None or r_.get("vote_cal") is None:
                r_[key] = None
                continue
            r_[key] = f"in:{r_['vote_cal']}" if hit else "out"
            member_w += b if hit else 0.0
        share = member_w / W
        if share <= 0.02:
            continue
        margins[key] = {f"in:{k}": share * v / tot for k, v in split.items()} | {"out": 1 - share}
        applied_segments.append(row["segment"])
    if "vote_cal" not in margins:
        raise HTTPException(422, "No topline poll split (candidate and opponent) to calibrate to.")
    # rake only where the vote bucket is known; non-voters keep their demographic weight share
    weights, diag = D.rake(rake_rows, base, margins, trim=(0.2, 5.0))
    by_id = dict(zip(ids, weights))
    full = store.find("agents", population_id=run["population_id"])
    for a in full:
        a["weight_cal"] = round(by_id[a["id"]], 5) if a["id"] in by_id else None
    store.upsert_many("agents", full)
    rows_after, _, _ = calibration_table(run, weight_key="weight_cal")
    diffs = [abs(r["diff"]) for r in rows_after if r.get("diff") is not None]
    mae_after = round(sum(diffs) / len(diffs), 2) if diffs else None
    res = dict(run.get("results") or {})
    res.update(applied=True, after=rows_after, mae_after=mae_after, deff=diag["deff"], applied_segments=applied_segments,
               raking=diag)
    store.update("sim_runs", run["id"], {"results": res})
    cal = dict(pop.get("calibration") or {})
    cal.update(applied=True, mae_after=mae_after, deff=diag["deff"], run_id=run["id"], candidate_id=run["candidate_id"])
    store.update("populations", run["population_id"], {"calibration": cal})
    return store.get("sim_runs", run["id"]) or run


# ---------------------------------------------------------------- backtest

FORMAT_BY_TYPE = {"speech": "speech_excerpt", "ad": "ad_script", "debate": "debate_clip", "social_post": "social_post",
                  "policy": "policy_summary"}


def eligible_events(cid: str) -> list[dict]:
    store = get_store()
    res = analytics.analyze(store.find("polls", candidate_id=cid), store.find("events", candidate_id=cid), "vote_share", "All")
    return [e for e in res["events"] if (e.get("impact") or {}).get("signal") not in (None, "insufficient")
            and (e.get("impact") or {}).get("delta") is not None]


def create_backtest(cid: str, body: BacktestIn) -> dict:
    cand = _candidate(cid)
    pop = get_store().get("populations", body.population_id)
    if not pop:
        raise HTTPException(404, "Population not found")
    events = eligible_events(cid)
    if body.event_ids:
        events = [e for e in events if e["id"] in set(body.event_ids)]
    events = events[:12]
    if not events:
        raise HTTPException(422, "No past events have enough polling before and after them to backtest.")
    agents = _ready_agents(body.population_id)
    if not agents:
        raise HTTPException(422, "This population has no ready agents yet.")
    chosen = _sample(agents, body.sample_size, f"backtest:{cid}")
    questions = [q for q in P.questionnaire("political", display_name(cand["name"]), display_name(cand.get("opponent_name", "")))
                 if q["id"] in ("vote_choice", "thermometer")]
    ev_cfg = []
    for e in events:
        as_of = date.fromisoformat(str(e["date"])) - timedelta(days=1)
        text = f"{e['type'].replace('_', ' ').title()} on {e['date']}: {e['title']}."
        if e.get("summary"):
            text += f"\n{e['summary']}"
        if e.get("content"):
            text += f"\n\n{str(e['content'])[:2000]}"
        ev_cfg.append({
            "id": e["id"], "date": str(e["date"]), "title": e["title"], "type": e.get("type"),
            "context": race_context(cand, as_of),
            "arm": {"id": "event", "label": e["title"], "kind": "treatment", "format": FORMAT_BY_TYPE.get(e.get("type"), "news_article"),
                    "source": "news coverage", "text": text, "control_mode": "placebo"},
            "measured": {k: e["impact"].get(k) for k in ("delta", "se", "z", "signal")},
            "segment_impacts": e.get("segment_impacts") or {},
        })
    per_unit_tok = costs.persona_tokens(pop.get("transcript_words") or 900, pop.get("reflections_per_expert") or 6)
    est = costs.estimate_panel(len(chosen) * len(ev_cfg), 2, 1, len(questions), per_unit_tok, 400)
    config = {
        "agent_ids": [a["id"] for a in chosen], "events": ev_cfg, "questions": questions,
        "arms": [{"id": "control", "label": "Placebo", "kind": "control", "control_mode": "placebo"}],
        "subject": display_name(cand["name"]), "opponent": display_name(cand.get("opponent_name", "")),
        "routes": {q["id"]: q["expert"] for q in questions}, "card_detail": pop.get("card_detail", "light"),
        "geography": pop.get("geography", ""), "weight_set": "demographic", "seed": 7,
    }
    total = len(chosen) * len(ev_cfg)
    return new_run("backtest", body.population_id, f"Backtest: {cand['name']}", config, total, est, candidate_id=cid)


def step(ctx: StepCtx) -> None:
    store = get_store()
    cfg = ctx.run["config"]
    events = cfg["events"]
    E = len(events)
    schema = make_panel_schema(cfg["questions"], "PanelAnswers")
    control = cfg["arms"][0]
    rid = ctx.run["id"]

    def process(ctx: StepCtx, idx: list[int]) -> None:
        cache: dict[str, dict] = {}
        units = []
        for i in idx:
            aid = cfg["agent_ids"][i // E]
            if aid not in cache:
                agent = store.get("agents", aid)
                if not agent:
                    continue
                cache[aid] = agent
            units.append((cache[aid], events[i % E]))
        docs = []
        bad = 0
        for arm_of in (lambda ev: control, lambda ev: ev["arm"]):
            items = [(agent, ev, arm_of(ev)) for agent, ev in units]
            for (agent, ev, arm), value, err in ctx.parallel(lambda it: agent_call(it[0], cfg, it[2], schema, it[1]["context"]), items):
                docs.append(response_doc(rid, agent["id"], arm["id"], 0, value, err, {"event_id": ev["id"]}))
                bad += err is not None
        if not ctx.save("sim_results", docs):
            return
        ctx.failed += bad
        ctx.done += len(units)

    batch_loop(ctx, len(cfg["agent_ids"]) * E, process, 2)


def finalize(ctx: StepCtx) -> None:
    """Simulated effects per event, then a slope against the measured poll movement.

    The predictor is the feeling thermometer, not simulated vote share: in a low-information race most agents
    stay "undecided", so vote share moves in lumps of one agent while the thermometer moves smoothly.
    β converts thermometer points into poll points."""
    res = backtest_results(ctx.run)
    ctx.patch["results"] = res
    ctx.note(f"Backtest β = {res['beta']} (r = {res['r']})")
    ctx.status = "done"


def backtest_results(run: dict) -> dict[str, Any]:
    """Aggregate a backtest run (no model calls) and record the fit on the population."""
    store = get_store()
    cfg = run["config"]
    vote_q = next(q for q in cfg["questions"] if q["id"] == "vote_choice")
    therm_q = next(q for q in cfg["questions"] if q["id"] == "thermometer")
    agents = {a["id"]: a for a in store.find("agents", fields=["demographics", "weight"], population_id=run["population_id"])
              if a["id"] in set(cfg["agent_ids"])}
    responses = store.find("sim_results", run_id=run["id"])
    preds = poll_segment_predicates(run["candidate_id"])
    rows = []
    for ev in cfg["events"]:
        ev_resp = [r for r in responses if r.get("event_id") == ev["id"]]
        records = metrics.agent_records(ev_resp, agents, cfg["questions"], "weight", False, "control")
        ds, ws, idx = metrics._paired(records, therm_q, "event", "control")
        lin = metrics.linearized(ds, ws)
        vds, vws, _ = metrics._paired(records, vote_q, "event", "control", vote_q["options"][0])
        vlin = metrics.linearized(vds, vws)
        segs = {}
        for label, pred in preds.items():
            sel = [(d, w) for d, w, i in zip(ds, ws, idx)
                   if pred(agents.get(records[i]["id"], {}).get("demographics", {}))]
            if len(sel) >= 5:
                l2 = metrics.linearized([d for d, _ in sel], [w for _, w in sel])
                measured = ev["segment_impacts"].get(label) or {}
                segs[label] = {"sim": metrics.r(l2["est"]), "sim_se": metrics.r(l2["se"]), "n": l2["n"],
                               "measured": measured.get("delta"), "measured_signal": measured.get("signal")}
        rows.append({"id": ev["id"], "title": ev["title"], "date": ev["date"], "type": ev["type"],
                     "sim": metrics.r(lin["est"]), "sim_se": metrics.r(lin["se"]), "n": lin["n"],
                     "sim_vote": metrics.r(vlin["est"]), "sim_vote_se": metrics.r(vlin["se"]),
                     "measured": ev["measured"].get("delta"), "measured_se": ev["measured"].get("se"),
                     "signal": ev["measured"].get("signal"), "segments": segs})
    fit = fit_slope(rows) | {"predictor": "thermometer"}
    store.update("populations", run["population_id"], {"backtest": {
        "candidate_id": run["candidate_id"], "run_id": run["id"], "at": utcnow(), **fit}})
    return {"events": rows, **fit, "n_agents": len(agents)}


def fit_slope(rows: list[dict]) -> dict[str, Any]:
    """Inverse-variance slope through the origin: measured ≈ β × simulated."""
    pts = [(r["sim"], r["measured"], (r.get("measured_se") or 1.0) ** 2 + (r.get("sim_se") or 0.0) ** 2)
           for r in rows if r.get("sim") is not None and r.get("measured") is not None]
    if len(pts) < 2:
        return {"beta": None, "beta_se": None, "r": None, "sign_agreement": None, "n_events": len(pts)}
    sxx = sum(s * s / v for s, _, v in pts)
    sxy = sum(s * m / v for s, m, v in pts)
    beta = sxy / sxx if sxx > 0 else None
    beta_se = math.sqrt(1 / sxx) if sxx > 0 else None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    # a correlation needs at least three events to mean anything
    rr = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy) if vx > 0 and vy > 0 and len(pts) >= 3 else None
    clear = [r for r in rows if r.get("signal") in ("clear", "strong") and r.get("sim") is not None and r.get("measured")]
    agree = sum(1 for r in clear if (r["sim"] > 0) == (r["measured"] > 0) and r["sim"] != 0)
    return {"beta": metrics.r(beta, 3), "beta_se": metrics.r(beta_se, 3), "r": metrics.r(rr, 3),
            "sign_agreement": metrics.r(agree / len(clear), 3) if clear else None, "n_clear": len(clear),
            "n_events": len(pts)}


def attach_backtest_adjustment(run: dict, res: dict) -> None:
    """If this population was backtested for this candidate, translate effects into expected poll movement:
    β × (effect on the backtest's predictor question)."""
    if not run.get("candidate_id") or not res.get("effects"):
        return
    pop = get_store().get("populations", run["population_id"]) or {}
    bt = pop.get("backtest") or {}
    if bt.get("candidate_id") != run["candidate_id"] or bt.get("beta") is None:
        return
    predictor = bt.get("predictor") or "vote_choice"
    q = next((q for q in run["config"]["questions"] if q["id"] == predictor), None)
    if not q:
        return
    beta, beta_se = bt["beta"], bt.get("beta_se") or 0.0
    adjusted = {}
    for t, per_q in res["effects"].items():
        cell = per_q.get(predictor) or {}
        if predictor == "vote_choice":
            cell = (cell.get("options") or {}).get(q["options"][0]) or {}
        if cell.get("est") is None:
            continue
        d, se_d = cell["est"], cell.get("se") or 0.0
        est = beta * d
        se = math.sqrt((beta * se_d) ** 2 + (d * beta_se) ** 2)
        adjusted[t] = {"est": metrics.r(est), "lo": metrics.r(est - 1.96 * se), "hi": metrics.r(est + 1.96 * se),
                       "raw": d}
    res["backtest_adjusted"] = {"beta": beta, "beta_se": beta_se, "r": bt.get("r"), "run_id": bt.get("run_id"),
                                "predictor": predictor, "effects": adjusted}


def failed_units(run: dict) -> list[int]:
    cfg = run["config"]
    E = len(cfg["events"])
    pos = {aid: i for i, aid in enumerate(cfg["agent_ids"])}
    evpos = {e["id"]: j for j, e in enumerate(cfg["events"])}
    bad = set()
    for r in get_store().find("sim_results", fields=["agent_id", "event_id", "status"], run_id=run["id"], status="error"):
        if r["agent_id"] in pos and r.get("event_id") in evpos:
            bad.add(pos[r["agent_id"]] * E + evpos[r["event_id"]])
    return sorted(bad)
