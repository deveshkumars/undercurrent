"""HTTP routes for simulations. Mounted from main.py behind the access-code dependency."""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from .. import llm
from ..config import get_settings
from ..storage import get_store
from . import candidate as C
from . import costs, demo, jobs, panel
from . import presets as P
from . import runner
from .models import (
    BacktestIn,
    BranchIn,
    CalibrationIn,
    EstimateIn,
    ImportChunk,
    ImportFinish,
    ImportStart,
    PanelIn,
    PopulationIn,
    PopulationPatch,
    ReweightIn,
    RunPatch,
    SocialIn,
    SurveyIn,
)


def require_sim() -> None:
    if not get_settings().sim_enabled:
        raise HTTPException(503, "Simulations need MONGODB_URI on this deployment (serverless instances don't share /tmp).")
    demo.ensure_loaded()


router = APIRouter(prefix="/api/sim", dependencies=[Depends(require_sim)])
cand_router = APIRouter(prefix="/api/candidates/{cid}/sim", dependencies=[Depends(require_sim)])

RUN_LIST_FIELDS = ["kind", "population_id", "candidate_id", "parent_run_id", "title", "status", "created_at",
                   "updated_at", "cursor", "total", "progress", "estimate", "error", "branch_tick", "demo"]


def _run(rid: str) -> dict:
    run = get_store().get("sim_runs", rid)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


def public_run(run: dict) -> dict:
    """Run without the bulky agent id list."""
    out = dict(run)
    cfg = dict(out.get("config") or {})
    if "agent_ids" in cfg:
        cfg["n_agents"] = len(cfg.pop("agent_ids"))
    out["config"] = cfg
    return out


# ---------------------------------------------------------------- meta & estimates


@router.get("/meta")
def sim_meta() -> dict:
    s = get_settings()
    from . import social

    return {
        "enabled": s.sim_enabled,
        "model": s.sim_model,
        "backend": s.llm_backend,
        "llm_ready": s.llm_backend == "claude-cli" or bool(s.anthropic_api_key),
        "presets": {k: {"label": v["label"], "description": v["description"], "margins": v["margins"]} for k, v in P.PRESETS.items()},
        "levels": P.LEVELS,
        "labels": P.LABELS,
        "level_labels": P.LEVEL_LABELS,
        "targetable": list(P.TARGETABLE),
        "questionnaires": {k: P.questionnaire(k, "{subject}", "{opponent}") for k in ("political", "product", "policy")},
        "formats": P.STIMULUS_FORMATS,
        "experts": P.EXPERT_RUBRIC,
        "intervention_templates": social.TEMPLATES,
        "limits": {"max_agents": s.sim_max_agents, "max_social_agents": s.sim_max_social_agents,
                   "max_calls_per_run": s.sim_max_calls_per_run, "concurrency": s.sim_concurrency},
        "pricing": dict(zip(("input", "output"), costs.prices())),
    }


@router.get("/demos")
def list_demos() -> dict:
    """The built-in demo population and runs (loaded from fixtures), for the home page."""
    from . import social

    store = get_store()
    data = demo.fixture()
    runs = store.find("sim_runs", sort="created_at", fields=RUN_LIST_FIELDS + ["results", "config"], demo=True)
    out = []
    for r in runs:
        res, cfg = r.pop("results", None) or {}, r.pop("config", None) or {}
        if r["kind"] == "panel" and res:
            arms = {a["id"]: a["label"] for a in cfg.get("arms", [])}
            prim = res.get("primary")
            r["highlight"] = {
                "headline": (res.get("summary") or {}).get("headline"),
                "arms": [{"label": arms.get(t, t), **{k: (e.get(prim) or {}).get(k) for k in ("est", "lo", "hi")}}
                         for t, e in (res.get("effects") or {}).items()],
            }
        elif r["kind"] == "social" and r.get("status") == "done":
            summary = social.compare(store.get("sim_runs", r["id"]) or r, [])["runs"][0]["summary"]
            r["highlight"] = {"ner": summary.get("ner"), "final_stance": summary.get("final_stance")}
        if r["kind"] != "populate":
            out.append(r)
    return {
        "populations": store.find("populations", fields=["name", "agent_count", "persona_mode", "source", "preset"], demo=True),
        "runs": out,
        "generated": (data or {}).get("generated"),
    }


@router.post("/estimate")
def estimate(body: EstimateIn) -> dict:
    c = body.config
    if body.kind == "populate":
        return costs.estimate_populate(int(c.get("size", 100)), c.get("persona_mode", "interview"),
                                       int(c.get("transcript_words", 900)), int(c.get("reflections_per_expert", 6)))
    if body.kind == "panel":
        return costs.estimate_panel(int(c.get("n", 100)), int(c.get("arms", 2)), int(c.get("replicates", 1)),
                                    int(c.get("questions", 9)), int(c.get("persona_tokens", 1800)), int(c.get("stimulus_tokens", 300)))
    return costs.estimate_social(int(c.get("n_agents", 60)), int(c.get("duration_hours", 12)), int(c.get("tick_minutes", 10)),
                                 int(c.get("max_calls_per_tick", 12)))


# ---------------------------------------------------------------- populations


@router.post("/populations/preview")
def population_preview(body: PopulationIn) -> dict:
    return jobs.preview(body)


@router.post("/populations", status_code=201)
def create_population(body: PopulationIn) -> dict:
    s = get_settings()
    if body.size > s.sim_max_agents:
        raise HTTPException(422, f"Populations are limited to {s.sim_max_agents} agents (SIM_MAX_AGENTS).")
    if body.candidate_id and not body.geography:
        cand = get_store().get("candidates", body.candidate_id)
        if cand and cand.get("jurisdiction"):
            body = body.model_copy(update={"geography": cand["jurisdiction"]})
    return jobs.create_synthetic(body)


@router.get("/populations")
def list_populations(candidate_id: str | None = None) -> list[dict]:
    filters: dict[str, Any] = {"candidate_id": candidate_id} if candidate_id else {}
    return get_store().find("populations", sort="-created_at", **filters)


@router.get("/populations/{pid}")
def get_population(pid: str) -> dict:
    pop = jobs.get_population(pid)
    if pop.get("populate_run_id"):
        run = get_store().get("sim_runs", pop["populate_run_id"])
        pop["populate_run"] = {k: run.get(k) for k in ("id", "status", "cursor", "total", "progress", "error")} if run else None
    return pop


@router.patch("/populations/{pid}")
def patch_population(pid: str, body: PopulationPatch) -> dict:
    jobs.get_population(pid)
    return get_store().update("populations", pid, body.model_dump(exclude_unset=True)) or {}


@router.delete("/populations/{pid}")
def delete_population(pid: str) -> dict:
    jobs.delete_population(pid)
    return {"deleted": True}


@router.post("/populations/{pid}/reweight")
def reweight(pid: str, body: ReweightIn) -> dict:
    return jobs.reweight(pid, body.targets)


@router.post("/populations/import", status_code=201)
def import_start(body: ImportStart) -> dict:
    return jobs.import_start(body)


@router.post("/populations/{pid}/import/chunk")
def import_chunk(pid: str, body: ImportChunk) -> dict:
    return jobs.import_chunk(pid, body.csv)


@router.post("/populations/{pid}/import/finish")
def import_finish(pid: str, body: ImportFinish) -> dict:
    return jobs.import_finish(pid, body)


@router.get("/populations/{pid}/agents")
def list_agents(
    pid: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: str | None = None,
) -> dict:
    jobs.get_population(pid)
    filters: dict[str, Any] = {"population_id": pid}
    if status:
        filters["persona_status"] = status
    store = get_store()
    return {
        "total": store.count("agents", **filters),
        "agents": store.find("agents", sort="index", fields=jobs.AGENT_LIST_FIELDS, limit=limit, skip=offset, **filters),
    }


@router.get("/agents/{aid}")
def get_agent(aid: str) -> dict:
    store = get_store()
    agent = store.get("agents", aid)
    if not agent:
        raise HTTPException(404, "Agent not found")
    responses = store.find("sim_results", agent_id=aid)[-40:]
    titles = {}
    for r in responses:
        if r["run_id"] not in titles:
            run = store.get("sim_runs", r["run_id"])
            titles[r["run_id"]] = run["title"] if run else "(deleted run)"
    agent["responses"] = [r | {"run_title": titles.get(r["run_id"], "")} for r in responses]
    return agent


# ---------------------------------------------------------------- runs


@router.post("/runs/panel", status_code=201)
def create_panel_run(body: PanelIn) -> dict:
    return public_run(panel.create_panel(body))


@router.post("/runs/social", status_code=201)
def create_social_run(body: SocialIn) -> dict:
    from . import social

    return public_run(social.create_social(body))


@router.post("/runs/survey", status_code=201)
def create_survey_run(body: SurveyIn) -> dict:
    from . import survey

    return public_run(survey.create_survey(body))


@router.get("/runs")
def list_runs(population_id: str | None = None, candidate_id: str | None = None, kind: str | None = None) -> list[dict]:
    filters = {k: v for k, v in (("population_id", population_id), ("candidate_id", candidate_id), ("kind", kind)) if v}
    return get_store().find("sim_runs", sort="-created_at", fields=RUN_LIST_FIELDS, **filters)


@router.get("/runs/{rid}")
def get_run(rid: str) -> dict:
    return public_run(_run(rid))


@router.patch("/runs/{rid}")
def patch_run(rid: str, body: RunPatch) -> dict:
    run = _run(rid)
    patch: dict[str, Any] = {}
    if body.title:
        patch["title"] = body.title
    if body.max_calls:
        patch["budget"] = dict(run.get("budget") or {}) | {"max_calls": body.max_calls}
    return public_run(get_store().update("sim_runs", rid, patch) or run)


@router.delete("/runs/{rid}")
def delete_run(rid: str) -> dict:
    _run(rid)
    jobs.delete_run(rid)
    return {"deleted": True}


@router.post("/runs/{rid}/step")
def step_run(rid: str) -> dict:
    return public_run(runner.step(rid))


def _set_status(rid: str, allowed: set[str], status: str, extra: dict | None = None) -> dict:
    run = _run(rid)
    if run["status"] not in allowed:
        raise HTTPException(409, f"Can't change a {run['status']} run to {status}.")
    return public_run(get_store().update("sim_runs", rid, {"status": status, **(extra or {})}) or run)


@router.post("/runs/{rid}/pause")
def pause_run(rid: str) -> dict:
    return _set_status(rid, {"pending", "running"}, "paused")


@router.post("/runs/{rid}/resume")
def resume_run(rid: str) -> dict:
    run = _run(rid)
    if run["status"] == "budget_exhausted" and run["progress"].get("calls", 0) >= run["budget"]["max_calls"]:
        raise HTTPException(409, "Raise the call budget before resuming.")
    status = "finalizing" if run["cursor"] >= run["total"] and not run.get("retry") and run["kind"] != "social" else "running"
    return _set_status(rid, {"paused", "budget_exhausted", "pending", "running"}, status, {"error": ""})


@router.post("/runs/{rid}/cancel")
def cancel_run(rid: str) -> dict:
    return _set_status(rid, {"pending", "running", "paused", "budget_exhausted", "finalizing"}, "canceled")


@router.post("/runs/{rid}/retry-failed")
def retry_failed(rid: str) -> dict:
    run = _run(rid)
    mod = runner._handler(run["kind"])
    if not hasattr(mod, "failed_units"):
        raise HTTPException(409, "This kind of run can't retry individual units.")
    units = mod.failed_units(run)
    if not units:
        raise HTTPException(409, "Nothing failed.")
    if run["status"] not in ("done", "paused", "budget_exhausted", "running", "pending"):
        raise HTTPException(409, f"Can't retry a {run['status']} run.")
    return public_run(get_store().update("sim_runs", rid, {"retry": units, "status": "running", "error": ""}) or run)


@router.post("/runs/{rid}/summarize")
def summarize_run(rid: str) -> dict:
    run = _run(rid)
    if run["kind"] != "panel" or run["status"] != "done":
        raise HTTPException(409, "Summaries are for finished panel runs.")
    res = dict(run.get("results") or {})
    try:
        summary, usage = panel.summarize(run, res)
    except llm.LLMError:
        raise
    res["summary"] = summary
    res.pop("summary_error", None)
    prog = dict(run["progress"])
    for k in runner.USAGE_KEYS:
        prog[k] = prog.get(k, 0) + int(usage.get(k) or 0)
    prog["calls"] = prog.get("calls", 0) + 1
    prog["usd"] = round(prog.get("usd", 0) + costs.usd(usage, run.get("model")), 5)
    return public_run(get_store().update("sim_runs", rid, {"results": res, "progress": prog}) or run)


@router.post("/runs/{rid}/recompute")
def recompute_run(rid: str) -> dict:
    run = _run(rid)
    if run["kind"] not in ("panel", "backtest") or run["status"] != "done":
        raise HTTPException(409, "Recompute works on finished panel and backtest runs.")
    results = panel.recompute(run) if run["kind"] == "panel" else C.backtest_results(run)
    return public_run(get_store().update("sim_runs", rid, {"results": results}) or run)


@router.get("/runs/{rid}/responses")
def run_responses(
    rid: str, arm: str | None = None, agent: str | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
) -> dict:
    _run(rid)
    filters: dict[str, Any] = {"run_id": rid}
    if arm:
        filters["arm_id"] = arm
    if agent:
        filters["agent_id"] = agent
    store = get_store()
    rows = store.find("sim_results", **filters)
    return {"total": len(rows), "responses": rows[offset: offset + limit]}


@router.get("/runs/{rid}/export.csv")
def export_csv(rid: str) -> Response:
    run = _run(rid)
    store = get_store()
    cfg = run["config"]
    questions = cfg.get("questions") or []
    agents = {a["id"]: a for a in store.find("agents", fields=["first_name", "demographics", "weight", "weight_cal", "source"],
                                             population_id=run["population_id"])}
    arms = {a["id"]: a["label"] for a in cfg.get("arms") or []}
    buf = io.StringIO()
    demo_cols = list(P.LEVELS) + ["age", "state"]
    w = csv.writer(buf)
    w.writerow(["agent_id", "name", "source", "weight", "weight_cal", *demo_cols, "arm", "event_id", "replicate", "status",
                "reasoning", *[q["id"] for q in questions]])
    for r in store.find("sim_results", run_id=rid):
        a = agents.get(r["agent_id"], {})
        demo = a.get("demographics", {})
        w.writerow([r["agent_id"], a.get("first_name", ""), a.get("source", ""), a.get("weight"), a.get("weight_cal"),
                    *[demo.get(c, "") for c in demo_cols], arms.get(r["arm_id"], r["arm_id"]), r.get("event_id", ""),
                    r.get("replicate", 0), r.get("status"), r.get("reasoning", ""),
                    *[(r.get("answers") or {}).get(q["id"], "") for q in questions]])
    name = "".join(c if c.isalnum() else "-" for c in run["title"].lower())[:60] or "simulation"
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"content-disposition": f'attachment; filename="{name}.csv"'})


@router.post("/runs/{rid}/apply-calibration")
def apply_calibration(rid: str) -> dict:
    return public_run(C.apply_calibration(_run(rid)))


# ---------------------------------------------------------------- social views


@router.get("/runs/{rid}/ticks")
def run_ticks(rid: str) -> list[dict]:
    from . import social

    return social.ticks_for(_run(rid))


@router.get("/runs/{rid}/posts")
def run_posts(rid: str, root: str | None = None, author: str | None = None, limit: int = Query(200, ge=1, le=2000)) -> dict:
    from . import social

    return social.posts_view(_run(rid), root=root, author=author, limit=limit)


@router.get("/runs/{rid}/network")
def run_network(rid: str) -> dict:
    from . import social

    return social.network_view(_run(rid))


@router.post("/runs/{rid}/branch", status_code=201)
def branch_run(rid: str, body: BranchIn) -> list[dict]:
    from . import social

    return [public_run(r) for r in social.branch(_run(rid), body)]


@router.get("/runs/{rid}/compare")
def compare_runs(rid: str, with_: str = Query("", alias="with")) -> dict:
    from . import social

    others = [_run(x) for x in with_.split(",") if x.strip()]
    return social.compare(_run(rid), others)


# ---------------------------------------------------------------- candidate hooks


@cand_router.get("")
def candidate_sim(cid: str) -> dict:
    C._candidate(cid)
    store = get_store()
    runs = store.find("sim_runs", sort="-created_at", fields=RUN_LIST_FIELDS, candidate_id=cid)
    pops = store.find("populations", sort="-created_at")
    return {
        "runs": runs,
        "populations": pops,
        "poll_segments": C.poll_segments(cid),
        "eligible_events": [{"id": e["id"], "date": e["date"], "title": e["title"], "type": e.get("type"),
                             "delta": e["impact"]["delta"], "signal": e["impact"]["signal"]} for e in C.eligible_events(cid)],
    }


@cand_router.get("/context")
def candidate_context(cid: str, as_of: date | None = None) -> dict:
    return {"context": C.race_context(C._candidate(cid), as_of or date.today())}


@cand_router.get("/segments")
def candidate_segments(cid: str, population_id: str) -> dict:
    C._candidate(cid)
    jobs.get_population(population_id)
    return C.segment_mapping(cid, population_id)


@cand_router.post("/calibration", status_code=201)
def candidate_calibration(cid: str, body: CalibrationIn) -> dict:
    return public_run(C.create_calibration(cid, body))


@cand_router.post("/backtest", status_code=201)
def candidate_backtest(cid: str, body: BacktestIn) -> dict:
    return public_run(C.create_backtest(cid, body))
