"""Undercurrent API. All routes live under /api so the same app serves locally and on Vercel."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import analytics, prompts
from .access import AccessMiddleware, LEVEL
from .ai_schemas import DraftFeatures, EventTags, ForecastOutput, InsightsOutput, RecommendationsOutput
from .config import ROOT, get_settings
from .importers import parse_events, parse_polls
from .llm import LLMError, structured
from .models import (
    Candidate,
    CandidateIn,
    CandidatePatch,
    CsvImport,
    Event,
    EventIn,
    ForecastRequest,
    InsightsRequest,
    Poll,
    PollIn,
    RecommendationsRequest,
    Report,
    TagEventRequest,
)
from .sample_data import build_demo
from .sim import jobs as sim_jobs
from .sim.routes import cand_router as sim_cand_router
from .sim.routes import router as sim_router
from .storage import get_store

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Undercurrent", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(AccessMiddleware)  # classifies every request: full / visitor (public demo, read-only) / 401


@app.exception_handler(LLMError)
async def _llm_error(_: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


def require_access(x_access_code: str | None = Header(default=None)) -> None:
    """Defense in depth behind AccessMiddleware: denied requests never get here, and visitors only reach
    the read-only routes it allows."""
    if LEVEL.get() == "deny":
        raise HTTPException(401, "Access code required")


public = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(require_access)])


# ---------------------------------------------------------------- meta


@public.get("/health")
def health() -> dict:
    return {"ok": True}


@public.get("/meta")
def meta() -> dict:
    s = get_settings()
    return {
        "llm_backend": s.llm_backend,
        "model": s.llm_model,
        "effort": s.llm_effort,
        "llm_ready": s.llm_backend == "claude-cli" or bool(s.anthropic_api_key),
        "storage": s.storage_backend,
        "access_required": bool(s.access_code) or s.public_demo,
        "public_demo": s.public_demo,
        "ephemeral_storage": s.on_vercel and s.storage_backend == "json-file",
        "sim": {
            "enabled": s.sim_enabled,
            "reason": "" if s.sim_enabled else "Simulations need MONGODB_URI on this deployment.",
            "model": s.sim_model,
        },
    }


@api.get("/auth/check")
def auth_check() -> dict:
    return {"ok": True}


FIXTURES = Path(__file__).parent / "sim" / "fixtures"


@api.get("/validation")
def validation_results() -> dict:
    """Scores from the last scripts/validate.py test run (derived scores only, no survey data), plus the
    classic-experiment replications from scripts/experiments.py when present."""
    path = FIXTURES / "validation.json"
    if not path.exists():
        raise HTTPException(404, "No validation results yet. Run scripts/validate.py --split test.")
    out = json.loads(path.read_text())
    exp = FIXTURES / "experiments.json"
    out["experiments"] = json.loads(exp.read_text()) if exp.exists() else None
    return out


# ---------------------------------------------------------------- helpers


def _candidate(cid: str) -> dict:
    cand = get_store().get("candidates", cid)
    if not cand:
        raise HTTPException(404, "Candidate not found")
    return cand


def _analysis(cid: str, metric: str, segment: str, window: int) -> dict:
    store = get_store()
    polls = store.find("polls", candidate_id=cid)
    events = store.find("events", candidate_id=cid)
    return analytics.analyze(polls, events, metric, segment, window)


def _topic_vocabulary(cid: str) -> list[str]:
    counts = Counter(t.strip().lower() for e in get_store().find("events", candidate_id=cid) for t in e.get("topics", []))
    return [t for t, _ in counts.most_common(40)]


def _save_report(cid: str, kind: str, params: dict, output: dict, usage: dict, quant: dict | None = None) -> dict:
    report = Report(
        candidate_id=cid, kind=kind, model=usage.get("model", get_settings().llm_model),  # type: ignore[arg-type]
        params=params, quant=(quant or {}) | {"usage": usage}, output=output,
    )
    return get_store().insert("reports", report.model_dump(mode="json"))


# ---------------------------------------------------------------- candidates


@api.get("/candidates")
def list_candidates() -> list[dict]:
    store = get_store()
    out = []
    for c in store.find("candidates", sort="created_at"):
        c["poll_count"] = len(store.find("polls", candidate_id=c["id"]))
        c["event_count"] = len(store.find("events", candidate_id=c["id"]))
        out.append(c)
    return out


@api.post("/candidates", status_code=201)
def create_candidate(body: CandidateIn) -> dict:
    return get_store().insert("candidates", Candidate(**body.model_dump()).model_dump(mode="json"))


@api.post("/candidates/demo", status_code=201)
def create_demo() -> dict:
    store = get_store()
    cand, polls, events = build_demo()
    store.insert("candidates", cand)
    store.insert_many("polls", polls)
    store.insert_many("events", events)
    return cand


@api.get("/candidates/{cid}")
def get_candidate(cid: str) -> dict:
    return _candidate(cid)


@api.patch("/candidates/{cid}")
def update_candidate(cid: str, body: CandidatePatch) -> dict:
    _candidate(cid)
    patch = body.model_dump(mode="json", exclude_unset=True)
    return get_store().update("candidates", cid, patch)  # type: ignore[return-value]


@api.delete("/candidates/{cid}")
def delete_candidate(cid: str) -> dict:
    store = get_store()
    _candidate(cid)
    for coll in ("polls", "events", "reports"):
        store.delete_many(coll, candidate_id=cid)
    for run in store.find("sim_runs", fields=["kind"], candidate_id=cid):
        sim_jobs.delete_run(run["id"])
    for pop in store.find("populations", fields=["candidate_id"], candidate_id=cid):
        store.update("populations", pop["id"], {"candidate_id": None})
    store.delete("candidates", cid)
    return {"deleted": True}


# ---------------------------------------------------------------- polls


@api.get("/candidates/{cid}/polls")
def list_polls(cid: str) -> list[dict]:
    _candidate(cid)
    return get_store().find("polls", sort="-date", candidate_id=cid)


@api.post("/candidates/{cid}/polls", status_code=201)
def add_poll(cid: str, body: PollIn) -> dict:
    _candidate(cid)
    return get_store().insert("polls", Poll(candidate_id=cid, **body.model_dump()).model_dump(mode="json"))


@api.post("/candidates/{cid}/polls/import")
def import_polls(cid: str, body: CsvImport) -> dict:
    _candidate(cid)
    parsed, errors, unmatched = parse_polls(body.csv)
    store = get_store()
    if body.replace and parsed:
        store.delete_many("polls", candidate_id=cid)
    docs = [Poll(candidate_id=cid, **p.model_dump()).model_dump(mode="json") for p in parsed]
    store.insert_many("polls", docs)
    return {"imported": len(docs), "errors": errors[:50], "error_count": len(errors), "ignored_columns": unmatched}


@api.delete("/candidates/{cid}/polls/{pid}")
def delete_poll(cid: str, pid: str) -> dict:
    poll = get_store().get("polls", pid)
    if not poll or poll["candidate_id"] != cid:
        raise HTTPException(404, "Poll not found")
    get_store().delete("polls", pid)
    return {"deleted": True}


# ---------------------------------------------------------------- events


@api.get("/candidates/{cid}/events")
def list_events(cid: str) -> list[dict]:
    _candidate(cid)
    return get_store().find("events", sort="-date", candidate_id=cid)


@api.post("/candidates/{cid}/events", status_code=201)
def add_event(cid: str, body: EventIn) -> dict:
    _candidate(cid)
    return get_store().insert("events", Event(candidate_id=cid, **body.model_dump()).model_dump(mode="json"))


@api.put("/candidates/{cid}/events/{eid}")
def update_event(cid: str, eid: str, body: EventIn) -> dict:
    ev = get_store().get("events", eid)
    if not ev or ev["candidate_id"] != cid:
        raise HTTPException(404, "Event not found")
    return get_store().update("events", eid, body.model_dump(mode="json"))  # type: ignore[return-value]


@api.delete("/candidates/{cid}/events/{eid}")
def delete_event(cid: str, eid: str) -> dict:
    ev = get_store().get("events", eid)
    if not ev or ev["candidate_id"] != cid:
        raise HTTPException(404, "Event not found")
    get_store().delete("events", eid)
    return {"deleted": True}


@api.post("/candidates/{cid}/events/import")
def import_events(cid: str, body: CsvImport) -> dict:
    _candidate(cid)
    parsed, errors, unmatched = parse_events(body.csv)
    store = get_store()
    if body.replace and parsed:
        store.delete_many("events", candidate_id=cid)
    docs = [Event(candidate_id=cid, **e.model_dump()).model_dump(mode="json") for e in parsed]
    store.insert_many("events", docs)
    return {"imported": len(docs), "errors": errors[:50], "error_count": len(errors), "ignored_columns": unmatched}


@api.post("/candidates/{cid}/events/tag")
def tag_event(cid: str, body: TagEventRequest) -> dict:
    _candidate(cid)
    if not (body.title or body.summary or body.content).strip():
        raise HTTPException(422, "Give the event a title, summary or content to tag.")
    vocab = sorted(set(_topic_vocabulary(cid)) | {t.lower() for t in body.existing_topics})
    tags, _ = structured(prompts.tag_task(body.title, body.summary, body.content, vocab), EventTags, effort="low")
    return tags.model_dump()


# ---------------------------------------------------------------- analysis (deterministic)


@api.get("/candidates/{cid}/analysis")
def analysis(
    cid: str,
    metric: str = Query("vote_share"),
    segment: str = Query("All"),
    window_days: int = Query(14, ge=3, le=60),
) -> dict:
    _candidate(cid)
    return _analysis(cid, metric, segment, window_days)


# ---------------------------------------------------------------- AI features


@api.post("/candidates/{cid}/insights")
def run_insights(cid: str, body: InsightsRequest) -> dict:
    cand = _candidate(cid)
    result = _analysis(cid, body.metric, body.segment, body.window_days)
    if not result["stats"].get("poll_count"):
        raise HTTPException(422, "Add polls for this metric and segment before running an analysis.")
    dossier = prompts.build_dossier(cand, result)
    output, usage = structured(prompts.insights_task(body.focus), InsightsOutput, dossier)
    return _save_report(cid, "insights", body.model_dump(mode="json"), output.model_dump(), usage)


@api.post("/candidates/{cid}/forecast")
def run_forecast(cid: str, body: ForecastRequest) -> dict:
    cand = _candidate(cid)
    result = _analysis(cid, body.metric, body.segment, body.window_days)
    draft = body.model_dump(mode="json")

    features, usage_a = structured(prompts.features_task(draft, _topic_vocabulary(cid)), DraftFeatures, effort="low")
    prior = analytics.find_analogs(result["events"], features.topics, body.type)
    segments = [s for s in result["dimensions"]["segments"] if s != body.segment]

    dossier = prompts.build_dossier(cand, result)
    output, usage_b = structured(prompts.forecast_task(draft, features.model_dump(), prior, segments), ForecastOutput, dossier)
    usage = usage_b | {
        "input_tokens": usage_a["input_tokens"] + usage_b["input_tokens"],
        "output_tokens": usage_a["output_tokens"] + usage_b["output_tokens"],
    }
    quant = {"features": features.model_dump(), "prior": prior, "current_average": result["stats"].get("latest")}
    return _save_report(cid, "forecast", draft, output.model_dump(), usage, quant)


@api.post("/candidates/{cid}/recommendations")
def run_recommendations(cid: str, body: RecommendationsRequest) -> dict:
    cand = _candidate(cid)
    result = _analysis(cid, body.metric, body.segment, body.window_days)
    if not result["stats"].get("poll_count") and not result["events"]:
        raise HTTPException(422, "Add polls or events before asking for recommendations.")
    latest = get_store().find("reports", sort="-created_at", candidate_id=cid, kind="insights")
    headline = latest[0]["output"].get("headline") if latest else None
    dossier = prompts.build_dossier(cand, result)
    output, usage = structured(prompts.recommendations_task(body.goal, headline), RecommendationsOutput, dossier)
    return _save_report(cid, "recommendations", body.model_dump(mode="json"), output.model_dump(), usage)


@api.get("/candidates/{cid}/reports")
def list_reports(cid: str, kind: str | None = None) -> list[dict]:
    _candidate(cid)
    filters: dict[str, Any] = {"candidate_id": cid}
    if kind:
        filters["kind"] = kind
    return get_store().find("reports", sort="-created_at", **filters)


@api.delete("/candidates/{cid}/reports/{rid}")
def delete_report(cid: str, rid: str) -> dict:
    rep = get_store().get("reports", rid)
    if not rep or rep["candidate_id"] != cid:
        raise HTTPException(404, "Report not found")
    get_store().delete("reports", rid)
    return {"deleted": True}


app.include_router(public)
app.include_router(api)
app.include_router(sim_router, dependencies=[Depends(require_access)])
app.include_router(sim_cand_router, dependencies=[Depends(require_access)])


# ---------------------------------------------------------------- built frontend (local single-process mode)

_dist = ROOT / "frontend" / "dist"
if _dist.exists() and not get_settings().on_vercel:
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        target = _dist / path
        if path and target.is_file() and Path(target).resolve().is_relative_to(_dist.resolve()):
            return FileResponse(target)
        return FileResponse(_dist / "index.html")

