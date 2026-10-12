"""Populations: synthetic generation, CSV import, reweighting, and the 'populate' run handler."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ..models import new_id, utcnow
from ..storage import get_store
from . import costs
from . import demographics as D
from .models import ImportFinish, ImportStart, PopulationIn
from .personas import generate_persona, generate_reflections, new_agent, parse_rows
from .runner import StepCtx, batch_loop, new_run

AGENT_LIST_FIELDS = [
    "population_id", "index", "source", "external_id", "demographics", "traits", "base_weight", "weight",
    "weight_cal", "persona_status", "persona_error", "first_name", "identity",
]


def get_population(pid: str) -> dict:
    pop = get_store().get("populations", pid)
    if not pop:
        raise HTTPException(404, "Population not found")
    return pop


def population_agents(pid: str, fields: list[str] | None = None, ready_only: bool = False) -> list[dict]:
    filters: dict[str, Any] = {"population_id": pid}
    if ready_only:
        filters["persona_status"] = "ready"
    return get_store().find("agents", sort="index", fields=fields or AGENT_LIST_FIELDS, **filters)


def preview(body: PopulationIn) -> dict:
    seed = body.seed if body.seed is not None else 1
    try:
        rows, base, margins = D.sample(body.size, body.preset, body.targets, body.oversample, seed)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    weights, diag = D.rake(rows, base, margins)
    return {
        "weighting": diag,
        "summary": D.summarize_population(rows, weights),
        "estimate": costs.estimate_populate(body.size, body.persona_mode, body.transcript_words, body.reflections_per_expert),
    }


def create_synthetic(body: PopulationIn) -> dict:
    store = get_store()
    seed = body.seed if body.seed is not None else int(new_id()[:8], 16)
    try:
        rows, base, margins = D.sample(body.size, body.preset, body.targets, body.oversample, seed)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    weights, diag = D.rake(rows, base, margins)
    pid = new_id()
    demographic_only = body.persona_mode == "demographic"
    agents = []
    for i, (row, b, w) in enumerate(zip(rows, base, weights)):
        if body.geography:
            row["state"] = body.geography
        agent = new_agent(pid, i, row, w, "synthetic", seed, base_weight=b)
        if demographic_only:
            agent["persona_status"] = "ready"
        agents.append(agent)
    pop = body.model_dump() | {
        "id": pid,
        "seed": seed,
        "created_at": utcnow(),
        "source": "synthetic",
        "status": "ready" if demographic_only else "generating",
        "agent_count": len(agents),
        "ready_count": len(agents) if demographic_only else 0,
        "weighting": diag,
        "summary": D.summarize_population(rows, weights),
        "calibration": None,
        "backtest": None,
        "populate_run_id": None,
    }
    store.insert_many("agents", agents)
    if not demographic_only:
        run = _populate_run(pop, [a["id"] for a in agents], "persona")
        pop["populate_run_id"] = run["id"]
    store.insert("populations", pop)
    return pop


def _populate_run(pop: dict, agent_ids: list[str], mode: str) -> dict:
    est = costs.estimate_populate(
        len(agent_ids), "interview", pop.get("transcript_words", 900), pop.get("reflections_per_expert", 6),
        imported=mode == "reflections",
    )
    title = f"Generate personas: {pop['name']}" if mode == "persona" else f"Expert reflections: {pop['name']}"
    return new_run("populate", pop["id"], title, {"agent_ids": agent_ids, "mode": mode}, len(agent_ids), est,
                   candidate_id=pop.get("candidate_id"))


def reweight(pid: str, targets: dict[str, dict[str, float]]) -> dict:
    store = get_store()
    pop = get_population(pid)
    agents = store.find("agents", sort="index", population_id=pid)
    rows = [a["demographics"] for a in agents]
    try:
        margins = D.effective_margins(pop.get("preset") or "us_registered_voters", targets)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if pop.get("source") == "csv":
        margins = {k: v for k, v in margins.items() if k in targets}  # imported samples: rake only to what was asked
    weights, diag = D.rake(rows, [a.get("base_weight") or 1.0 for a in agents], margins)
    for a, w in zip(agents, weights):
        a["weight"] = round(w, 5)
    store.upsert_many("agents", agents)
    return store.update("populations", pid, {"targets": targets, "weighting": diag,
                                             "summary": D.summarize_population(rows, weights)}) or pop


# ---------------------------------------------------------------- CSV import


def import_start(body: ImportStart) -> dict:
    if not body.consent_attested:
        raise HTTPException(422, "Confirm that respondents consented to their answers being used this way.")
    pop = {
        "id": new_id(),
        "name": body.name,
        "description": body.description,
        "created_at": utcnow(),
        "source": "csv",
        "status": "draft",
        "preset": "us_registered_voters",
        "targets": {},
        "oversample": {},
        "persona_mode": "interview",
        "card_detail": body.card_detail,
        "transcript_words": 0,
        "reflections_per_expert": body.reflections_per_expert,
        "geography": body.geography,
        "candidate_id": body.candidate_id,
        "seed": 0,
        "agent_count": 0,
        "ready_count": 0,
        "weighting": {},
        "summary": {},
        "calibration": None,
        "backtest": None,
        "populate_run_id": None,
        "consent_attested": True,
        "import": {"mode": body.mode, "chunks": 0, "rows": 0, "pii_dropped": [], "mapping": {}, "unknown_values": {}},
    }
    get_store().insert("populations", pop)
    return pop


def import_chunk(pid: str, csv_text: str) -> dict:
    store = get_store()
    pop = get_population(pid)
    if pop.get("source") != "csv" or pop.get("status") != "draft":
        raise HTTPException(409, "This population is not accepting imports.")
    try:
        parsed = parse_rows(csv_text, pop["import"]["mode"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    start = pop["agent_count"]
    if start + len(parsed["rows"]) > 5000:
        raise HTTPException(422, "Imports are limited to 5,000 respondents per population.")
    agents = []
    for i, r in enumerate(parsed["rows"]):
        agent = new_agent(pid, start + i, r["demographics"], r["weight"],
                          "csv_interview" if r["transcript"] else "csv_survey", pid, base_weight=r["weight"])
        agent.update(raw=r["raw"], transcript=r["transcript"], external_id=r["external_id"])
        agents.append(agent)
    store.insert_many("agents", agents)
    imp = pop["import"]
    unknown = imp.get("unknown_values") or {}
    for field, vals in parsed["unknown_values"].items():
        merged = unknown.setdefault(field, {})
        for k, c in vals.items():
            merged[k] = merged.get(k, 0) + c
    imp.update(
        chunks=imp["chunks"] + 1,
        rows=imp["rows"] + len(agents),
        pii_dropped=sorted(set(imp["pii_dropped"]) | set(parsed["columns"]["pii_dropped"])),
        mapping=imp["mapping"] or parsed["columns"]["mapping"],
        answer_columns=len(parsed["columns"]["answer_columns"]),
        unknown_values=unknown,
    )
    store.update("populations", pid, {"agent_count": start + len(agents), "import": imp})
    return {"imported": len(agents), "total": start + len(agents), "columns": parsed["columns"],
            "unknown_values": parsed["unknown_values"]}


def import_finish(pid: str, body: ImportFinish) -> dict:
    store = get_store()
    pop = get_population(pid)
    if pop.get("source") != "csv" or pop.get("status") != "draft":
        raise HTTPException(409, "This import is already finished.")
    agents = store.find("agents", sort="index", population_id=pid)
    if not agents:
        raise HTTPException(422, "No respondents were imported.")
    rows = [a["demographics"] for a in agents]
    base = [a.get("base_weight") or 1.0 for a in agents]
    mean = sum(base) / len(base) or 1.0
    base = [b / mean for b in base]
    margins = D.effective_margins(body.preset, body.targets) if body.rake else {}
    if body.rake and not body.targets:
        # rake only on the demographics the file actually has
        margins = {k: v for k, v in margins.items() if any(r.get(k) is not None for r in rows)}
    weights, diag = D.rake(rows, base, margins) if margins else (base, {
        "converged": True, "iterations": 0, "margins": D.composition(rows, base), "deff": round(D.design_effect(base), 3),
        "n_eff": round(len(base) / D.design_effect(base), 1), "trimmed": 0, "warnings": [],
    })
    for a, w in zip(agents, weights):
        a["weight"] = round(w, 5)
        if not body.generate_reflections:
            a["persona_status"] = "ready"
    store.upsert_many("agents", agents)
    patch: dict[str, Any] = {
        "preset": body.preset,
        "targets": body.targets,
        "weighting": diag,
        "summary": D.summarize_population(rows, weights),
        "status": "generating" if body.generate_reflections else "ready",
        "ready_count": 0 if body.generate_reflections else len(agents),
    }
    if body.generate_reflections:
        run = _populate_run(pop | patch, [a["id"] for a in agents], "reflections")
        patch["populate_run_id"] = run["id"]
    return store.update("populations", pid, patch) or pop


# ---------------------------------------------------------------- run handler: populate


def step(ctx: StepCtx) -> None:
    store = get_store()
    run = ctx.run
    pid = run["population_id"]
    pop = get_population(pid)
    agent_ids: list[str] = run["config"]["agent_ids"]
    generate = generate_persona if run["config"]["mode"] == "persona" else generate_reflections

    def one(agent: dict) -> tuple[dict, dict]:
        patch, usage = generate(agent, pop)
        patch["usage"] = usage
        return patch, usage

    def process(ctx: StepCtx, idx: list[int]) -> None:
        agents = [a for a in (store.get("agents", agent_ids[i]) for i in idx) if a]
        docs, ok, bad = [], 0, 0
        for agent, patch, err in ctx.parallel(one, agents):
            if err is not None:
                agent.update(persona_status="failed", persona_error=err.message)
                bad += 1
            else:
                agent.update(patch)
                ok += 1
            docs.append(agent)
        if not ctx.save("agents", docs):
            return
        ctx.done += ok
        ctx.failed += bad
        ready = store.count("agents", population_id=pid, persona_status="ready")
        store.update("populations", pid, {"ready_count": ready, "status": "generating"})

    batch_loop(ctx, len(agent_ids), process, 1)


def finalize(ctx: StepCtx) -> None:
    store = get_store()
    pid = ctx.run["population_id"]
    ready = store.count("agents", population_id=pid, persona_status="ready")
    failed = store.count("agents", population_id=pid, persona_status="failed")
    store.update("populations", pid, {"ready_count": ready, "status": "ready" if ready else "failed"})
    ctx.patch["results"] = {"ready": ready, "failed": failed}
    ctx.note(f"{ready} personas ready" + (f", {failed} failed (use Retry failed)" if failed else ""))
    ctx.status = "done"


def failed_units(run: dict) -> list[int]:
    store = get_store()
    ids = run["config"]["agent_ids"]
    failed = {a["id"] for a in store.find("agents", fields=["persona_status"], population_id=run["population_id"],
                                           persona_status="failed")}
    return [i for i, aid in enumerate(ids) if aid in failed]


def delete_population(pid: str) -> None:
    store = get_store()
    get_population(pid)
    for run in store.find("sim_runs", fields=["kind"], population_id=pid):
        delete_run(run["id"])
    store.delete_many("agents", population_id=pid)
    store.delete("populations", pid)


def delete_run(rid: str) -> None:
    store = get_store()
    for coll in ("sim_results", "sim_posts", "sim_ticks", "sim_checkpoints"):
        store.delete_many(coll, run_id=rid)
    store.delete("sim_state", rid)
    store.delete("sim_runs", rid)
