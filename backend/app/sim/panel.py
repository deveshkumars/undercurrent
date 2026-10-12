"""Panel message tests (Park et al. 2024 style).

Every sampled agent answers the same questionnaire once per arm (control first, then each treatment).
Agents are stateless across calls, so this is a within-subject counterfactual: effects are paired
differences. The persona block is cached, so arms after the control read it from the prompt cache.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from .. import llm
from ..config import get_settings
from ..models import new_id
from ..storage import get_store
from . import costs, metrics
from . import demographics as D
from . import presets as P
from . import prompts as SP
from .models import PanelIn
from .runner import StepCtx, batch_loop, new_run
from .sampling import rng_for
from .schemas import FocusGroupSummary, RoutingOutput, make_panel_schema

log = logging.getLogger("undercurrent.sim")

SCHEMA_NAME = "PanelAnswers"  # stable across a run: the output schema is part of the prompt-cache key


def _ready_agents(pid: str) -> list[dict]:
    return get_store().find(
        "agents", sort="index", fields=["index", "demographics", "weight", "weight_cal", "first_name"],
        population_id=pid, persona_status="ready",
    )


def _sample(agents: list[dict], k: int | None, seed: Any) -> list[dict]:
    if not k or k >= len(agents):
        return agents
    rng = rng_for("panel-sample", seed)
    chosen = rng.sample(agents, k)
    return sorted(chosen, key=lambda a: a["index"])


def build_questions(questionnaire: str, subject: str, opponent: str, custom: list[dict]) -> list[dict]:
    questions = P.questionnaire(questionnaire, subject, opponent) if questionnaire != "custom" else []
    ids = {q["id"] for q in questions}
    for q in custom:
        if q["id"] in ids:
            raise HTTPException(422, f"Question id '{q['id']}' is already used by the {questionnaire} questionnaire.")
        ids.add(q["id"])
        questions.append(q)
    if not questions:
        raise HTTPException(422, "Add at least one question.")
    if len(questions) > 14:
        raise HTTPException(422, "Use at most 14 questions per panel.")
    if not any(q["kind"] != "open" for q in questions):
        raise HTTPException(422, "Include at least one closed (choice or scale) question.")
    if not any(q.get("primary") for q in questions):
        first_numeric = next((q for q in questions if metrics.is_numeric(q)), None)
        if first_numeric:
            first_numeric["primary"] = True
    return questions


def create_panel(body: PanelIn, kind: str = "panel", extra_config: dict | None = None) -> dict:
    store = get_store()
    s = get_settings()
    pop = store.get("populations", body.population_id)
    if not pop:
        raise HTTPException(404, "Population not found")
    subject, opponent = body.subject.strip(), body.opponent.strip()
    if body.candidate_id:
        cand = store.get("candidates", body.candidate_id)
        if not cand:
            raise HTTPException(404, "Candidate not found")
        from .candidate import display_name

        subject = subject or display_name(cand["name"])
        opponent = opponent or display_name(cand.get("opponent_name", ""))
    agents = _ready_agents(body.population_id)
    if not agents:
        raise HTTPException(422, "This population has no ready agents yet; let persona generation finish first.")
    seed = body.seed if body.seed is not None else int(new_id()[:7], 16)
    chosen = _sample(agents, body.sample_size, seed)
    if len(chosen) > s.sim_max_agents:
        raise HTTPException(422, f"Panels are limited to {s.sim_max_agents} agents (SIM_MAX_AGENTS); set a sample size.")
    questions = build_questions(body.questionnaire, subject or "the subject", opponent,
                                [q.model_dump() for q in body.questions])
    arms = sorted([a.model_dump() for a in body.arms], key=lambda a: a["kind"] != "control")
    routes = {q["id"]: q["expert"] for q in questions if q.get("expert")}
    needs_routing = any(not q.get("expert") for q in questions)

    persona_tok = 400 if pop.get("persona_mode") == "demographic" else costs.persona_tokens(
        pop.get("transcript_words") or 900, pop.get("reflections_per_expert") or 6)
    stim_tok = int(sum(len(a.get("text") or "") for a in arms) / max(1, len(arms)) / 4) + 60
    est = costs.estimate_panel(len(chosen), len(arms), body.replicates, len(questions), persona_tok, stim_tok)
    if needs_routing:
        est["calls"] += 1
    config = {
        "agent_ids": [a["id"] for a in chosen],
        "arms": arms,
        "questions": questions,
        "context": body.context,
        "subject": subject,
        "opponent": opponent,
        "questionnaire": body.questionnaire,
        "replicates": body.replicates,
        "weight_set": body.weight_set,
        "likely_voter": body.likely_voter,
        "seed": seed,
        "routes": routes,
        "needs_routing": needs_routing,
        "card_detail": pop.get("card_detail", "light"),
        "geography": pop.get("geography", ""),
        "source_report_id": body.source_report_id,
    } | (extra_config or {})
    return new_run(kind, body.population_id, body.title, config, len(chosen), est, candidate_id=body.candidate_id)


# ---------------------------------------------------------------- calls


def _clamp(q: dict, value: Any) -> Any:
    if q["kind"] == "scale":
        try:
            return int(min(q["scale_max"], max(q["scale_min"], round(float(value)))))
        except (TypeError, ValueError):
            return None
    if q["kind"] == "single_choice":
        return value if value in q["options"] else None
    return str(value or "").strip()[:400]


def agent_call(agent: dict, cfg: dict, arm: dict, schema: type, context: str | None = None) -> tuple[dict, dict]:
    s = get_settings()
    questions = cfg["questions"]
    block = SP.persona_block(agent, cfg.get("card_detail", "light"), cfg.get("geography", ""))
    task = SP.panel_task(agent.get("first_name", ""), cfg["context"] if context is None else context, arm, questions,
                         cfg.get("routes") or {}, placebo_index=agent.get("index", 0))
    out, usage = llm.structured(
        task,
        schema,
        system=SP.AGENT_SYSTEM,
        cache_system=True,
        blocks=[llm.Block(block, cache=True)],
        effort=s.sim_agent_effort,
        thinking=s.sim_agent_thinking,  # type: ignore[arg-type]
        model=s.sim_model,
        max_tokens=1500 + 150 * len(questions),
        timeout=s.sim_call_timeout,
        max_retries=1,
        log_level=logging.DEBUG,
    )
    answers = {q["id"]: _clamp(q, getattr(out, f"q_{q['id']}", None)) for q in questions}
    return {"reasoning": str(out.reasoning or "").strip()[:800], "answers": answers}, usage


def _route(ctx: StepCtx) -> None:
    cfg = ctx.run["config"]
    pending = [q for q in cfg["questions"] if q["id"] not in (cfg.get("routes") or {})]
    s = get_settings()
    routes = dict(cfg.get("routes") or {})
    try:
        out, usage = llm.structured(SP.routing_task(pending), RoutingOutput, system=SP.ANALYST_SYSTEM, effort="low",
                                    thinking="off", model=s.sim_model, max_tokens=2000, timeout=s.sim_call_timeout)
        ctx.add_usage(usage)
        for rt in out.routes:
            if rt.question_id in {q["id"] for q in pending}:
                routes[rt.question_id] = rt.expert
    except llm.LLMError as e:
        if e.status_code == 503:
            raise
        ctx.note(f"Expert routing failed ({e.message}); using the political scientist for custom questions.")
    for q in pending:
        routes.setdefault(q["id"], "political_scientist")
    cfg = cfg | {"routes": routes, "needs_routing": False}
    ctx.run["config"] = cfg
    ctx.patch["config"] = cfg


def response_doc(run_id: str, agent_id: str, arm_id: str, rep: int, value: dict | None, err: llm.LLMError | None,
                 extra: dict | None = None) -> dict:
    doc = {
        "id": f"{run_id}:{agent_id}:{arm_id}:{rep}" + (f":{extra['event_id']}" if extra and extra.get("event_id") else ""),
        "run_id": run_id, "agent_id": agent_id, "arm_id": arm_id, "replicate": rep,
        "status": "ok" if err is None else "error",
        "reasoning": (value or {}).get("reasoning", ""),
        "answers": (value or {}).get("answers", {}),
        "error": err.message if err else "",
    }
    return doc | (extra or {})


def step(ctx: StepCtx) -> None:
    store = get_store()
    cfg = ctx.run["config"]
    if cfg.get("needs_routing"):
        _route(ctx)
        cfg = ctx.run["config"]
    schema = make_panel_schema(cfg["questions"], SCHEMA_NAME)
    arms = cfg["arms"]
    control, rest = arms[0], arms[1:]
    reps = int(cfg.get("replicates") or 1)
    rid = ctx.run["id"]

    def process(ctx: StepCtx, idx: list[int]) -> None:
        agents = [a for a in (store.get("agents", cfg["agent_ids"][i]) for i in idx) if a]
        # phase 0 writes each persona to the prompt cache; phase 1 reads it for every other arm/replicate
        first = [(a, control, 0) for a in agents]
        later = [(a, arm, rep) for a in agents for arm in [control, *rest] for rep in range(reps) if (arm, rep) != (control, 0)]
        docs = []
        failed_agents: set[str] = set()
        for wave in (first, later):
            results = ctx.parallel(lambda item: agent_call(item[0], cfg, item[1], schema), wave)
            for (agent, arm, rep), value, err in results:
                docs.append(response_doc(rid, agent["id"], arm["id"], rep, value, err))
                if err is not None:
                    failed_agents.add(agent["id"])
        if not ctx.save("sim_results", docs):
            return
        ctx.failed += len(failed_agents)
        ctx.done += len(agents) - len(failed_agents)

    calls_per_unit = len(arms) * reps
    batch_loop(ctx, len(cfg["agent_ids"]), process, calls_per_unit)


def failed_units(run: dict) -> list[int]:
    ids = run["config"]["agent_ids"]
    bad = {r["agent_id"] for r in get_store().find("sim_results", fields=["agent_id", "status"], run_id=run["id"], status="error")}
    return [i for i, aid in enumerate(ids) if aid in bad]


# ---------------------------------------------------------------- aggregation


def _short_label(demo: dict) -> str:
    bits = []
    if demo.get("age") is not None:
        bits.append(str(demo["age"]))
    elif demo.get("age_band"):
        bits.append(demo["age_band"])
    if demo.get("gender"):
        bits.append({"female": "F", "male": "M"}.get(demo["gender"], demo["gender"]))
    if demo.get("race"):
        bits.append(demo["race"])
    party = demo.get("party")
    if party:
        lean = demo.get("lean")
        bits.append({"democrat": "Dem", "republican": "Rep"}.get(party, "Ind" + (f"→{lean.title()}" if lean in ("dem", "rep") else "")))
    if demo.get("education"):
        bits.append(P.LEVEL_LABELS.get(demo["education"], demo["education"]))
    return " · ".join(bits)


def segments_for(agents: dict[str, dict], candidate_id: str | None) -> tuple[dict[str, dict[str, str]], list[str]]:
    segs = {aid: D.segment_levels(a.get("demographics", {})) for aid, a in agents.items()}
    unmapped: list[str] = []
    if candidate_id:
        from . import candidate as C

        for label, pred in C.poll_segment_predicates(candidate_id, unmapped).items():
            for aid, a in agents.items():
                hit = pred(a.get("demographics", {}))
                if hit is not None:
                    segs[aid][f"poll: {label}"] = "in segment" if hit else "outside"
    return segs, unmapped


def aggregate(run: dict) -> dict[str, Any]:
    store = get_store()
    cfg = run["config"]
    questions = cfg["questions"]
    arms = cfg["arms"]
    control = arms[0]["id"]
    treatments = [a["id"] for a in arms[1:]]
    responses = store.find("sim_results", run_id=run["id"])
    agent_docs = {a["id"]: a for a in store.find(
        "agents", fields=["index", "demographics", "weight", "weight_cal", "first_name", "source"],
        population_id=run["population_id"],
    ) if a["id"] in set(cfg["agent_ids"])}
    weight_key = "weight_cal" if cfg.get("weight_set") == "calibrated" else "weight"
    records = metrics.agent_records(responses, agent_docs, questions, weight_key, bool(cfg.get("likely_voter")), control)
    segs, unmapped = segments_for(agent_docs, run.get("candidate_id"))

    # persuadables: undecided or lukewarm under the control arm
    for rec in records:
        ctrl_cat = rec["cat"].get(control, {}).get("vote_choice") or {}
        therm = rec["num"].get(control, {}).get("thermometer")
        if ctrl_cat or therm is not None:
            persuadable = ctrl_cat.get("undecided", 0) >= 0.5 or (therm is not None and 35 <= therm <= 65)
            segs.setdefault(rec["id"], {})["persuadable"] = "persuadable" if persuadable else "committed"

    tops = metrics.toplines(records, questions, [control, *treatments])
    effects = metrics.paired_effects(records, questions, treatments, control, seed=cfg.get("seed", 0)) if treatments else {}
    primary = next((q for q in questions if q.get("primary")), None)
    seg_cells: list[dict] = []
    if primary and treatments:
        seg_cells = metrics.segment_effects(records, segs, primary, treatments, control)
    vote_q = next((q for q in questions if q["id"] == "vote_choice"), None)
    vote_cells: list[dict] = []
    trans: dict[str, Any] = {}
    if vote_q and treatments:
        vote_cells = metrics.segment_effects(records, segs, vote_q, treatments, control, opt=vote_q["options"][0])
        trans = {t: metrics.transitions(records, vote_q, t, control) for t in treatments}

    quotes = _quotes(records, agent_docs, questions, arms, primary, cfg.get("seed", 0))
    n_resp = len(responses)
    n_err = sum(1 for r in responses if r.get("status") != "ok")
    weights = [rec["w"] for rec in records]
    return {
        "n_agents": len(records),
        "n_responses": n_resp,
        "n_errors": n_err,
        "n_eff": round(metrics.n_eff(weights), 1) if weights else 0,
        "weight_set": cfg.get("weight_set", "demographic"),
        "primary": primary["id"] if primary else None,
        "toplines": tops,
        "effects": effects,
        "segments": seg_cells,
        "vote_segments": vote_cells,
        "transitions": trans,
        "quotes": quotes,
        "unmapped_poll_segments": unmapped,
        "sources": sorted({a.get("source", "synthetic") for a in agent_docs.values()}),
    }


def _quotes(records: list[dict], agents: dict[str, dict], questions: list[dict], arms: list[dict],
            primary: dict | None, seed: Any, limit: int = 60) -> list[dict]:
    """Stratified quotes: per arm, favor agents whose primary outcome moved most, plus a few at random."""
    open_ids = [q["id"] for q in questions if q["kind"] == "open"]
    control = arms[0]["id"]
    rng = rng_for("quotes", seed)
    out = []
    per_arm = max(4, limit // max(1, len(arms)))
    for arm in arms:
        cands = []
        for rec in records:
            texts = rec["open"].get(arm["id"], {})
            if not any(texts.get(q) for q in open_ids):
                continue
            delta = None
            if primary and arm["id"] != control:
                a = rec["num"].get(arm["id"], {}).get(primary["id"])
                b = rec["num"].get(control, {}).get(primary["id"])
                if a is not None and b is not None:
                    delta = a - b
            cands.append((rec, texts, delta))
        cands.sort(key=lambda c: -abs(c[2] or 0))
        top = cands[: per_arm // 2]
        rest = cands[per_arm // 2:]
        rng.shuffle(rest)
        party_seen: dict[str, int] = {}
        for rec, texts, delta in top + rest:
            if len([o for o in out if o["arm_id"] == arm["id"]]) >= per_arm:
                break
            demo = agents[rec["id"]].get("demographics", {})
            party = demo.get("party") or "unknown"
            if party_seen.get(party, 0) >= per_arm // 2 + 1:
                continue
            party_seen[party] = party_seen.get(party, 0) + 1
            out.append({
                "agent_id": rec["id"],
                "arm_id": arm["id"],
                "arm": arm["label"],
                "name": agents[rec["id"]].get("first_name", ""),
                "who": _short_label(demo),
                "delta": metrics.r(delta, 1),
                "texts": {q: texts[q][0] for q in open_ids if texts.get(q)},
                "reasoning": (rec["reasoning"].get(arm["id"]) or [""])[0],
            })
    return out


def _digest(run: dict, res: dict) -> str:
    cfg = run["config"]
    arms = {a["id"]: a for a in cfg["arms"]}
    lines = [f"Title: {run['title']}", f"Subject: {cfg.get('subject') or 'n/a'}",
             f"Simulated respondents: {res['n_agents']} (effective n {res['n_eff']})", "", "Arms:"]
    for a in cfg["arms"]:
        body = (a.get("text") or "").strip()
        lines.append(f"- {a['label']} ({a['kind']}): " + (body[:1200] + ("…" if len(body) > 1200 else "") if body else
                                                          ("placebo news brief" if a.get("control_mode") == "placebo" else "no message")))
    lines.append("")
    lines.append("Toplines by arm:")
    for q in cfg["questions"]:
        if q["kind"] == "open":
            continue
        cells = []
        for arm_id, per_q in res["toplines"].items():
            e = per_q.get(q["id"], {})
            if "mean" in e:
                cells.append(f"{arms[arm_id]['label']}: mean {e['mean']}")
            elif "shares" in e:
                top = sorted(((v or 0, k) for k, v in e["shares"].items()), reverse=True)[:3]
                cells.append(f"{arms[arm_id]['label']}: " + ", ".join(f"{k} {v * 100:.0f}%" for v, k in top))
        lines.append(f"- {q['id']}: " + " | ".join(cells))
    if res["effects"]:
        lines.append("")
        lines.append("Paired effects vs control (95% interval):")
        for t, per_q in res["effects"].items():
            for qid, e in per_q.items():
                if e.get("est") is not None:
                    lines.append(f"- {arms[t]['label']} · {qid}: {e['est']:+.1f} [{e.get('lo')}, {e.get('hi')}] n={e.get('n')}")
                for opt, oe in (e.get("options") or {}).items():
                    if oe.get("est") is not None and abs(oe["est"]) >= 3:
                        lines.append(f"- {arms[t]['label']} · {qid}={opt}: {oe['est']:+.1f} pp [{oe.get('lo')}, {oe.get('hi')}]")
    notable = [c for c in res["segments"] if not c["small"] and (c["fdr"] or abs(c["est"] or 0) >= 5)]
    notable.sort(key=lambda c: -abs(c["est"] or 0))
    if notable:
        lines.append("")
        lines.append(f"Segment effects on {res['primary']} (FDR flag = survives multiple-comparison correction):")
        for c in notable[:24]:
            lines.append(f"- {arms[c['treatment']]['label']} · {c['dim']}={c['level']}: {c['est']:+.1f} [{c['lo']}, {c['hi']}] "
                         f"n={c['n']}{' FDR' if c['fdr'] else ''}")
    lines.append("")
    lines.append("Quotes (respondent · arm · change in primary outcome):")
    for qt in res["quotes"][:60]:
        texts = " / ".join(qt["texts"].values())
        lines.append(f"- [{qt['who']} · {qt['arm']} · Δ{qt['delta'] if qt['delta'] is not None else 'n/a'}] {texts}")
    return "\n".join(lines)


def summarize(run: dict, res: dict) -> tuple[dict, dict]:
    s = get_settings()
    out, usage = llm.structured(SP.summary_task(_digest(run, res)), FocusGroupSummary, system=SP.ANALYST_SYSTEM,
                                effort="medium", model=s.sim_model, max_tokens=12000, timeout=s.sim_call_timeout * 2)
    return out.model_dump(), usage


def finalize(ctx: StepCtx) -> None:
    run = ctx.run
    if run["kind"] == "calibration":
        from . import candidate as C

        C.finalize_calibration(ctx)
        return
    res = aggregate(run)
    from . import candidate as C

    C.attach_backtest_adjustment(run, res)
    try:
        summary, usage = summarize(run, res)
        ctx.add_usage(usage)
        res["summary"] = summary
    except llm.LLMError as e:
        if e.status_code == 503:
            raise
        res["summary"] = None
        res["summary_error"] = e.message
        ctx.note(f"Summary failed: {e.message} (use Summarize to retry)")
    ctx.patch["results"] = res
    ctx.status = "done"


def recompute(run: dict) -> dict:
    res = aggregate(run)
    from . import candidate as C

    C.attach_backtest_adjustment(run, res)
    old = run.get("results") or {}
    res["summary"] = old.get("summary")
    if old.get("summary_error"):
        res["summary_error"] = old["summary_error"]
    return res
