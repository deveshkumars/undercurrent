"""Closed-ended survey runs: every sampled agent answers a questionnaire split into blocks of N
questions, one structured call per block, through the usual step protocol.

Used by the validation harness (scripts/validate.py) to ask real survey questions. Agents only see
question wording and options. The persona block is cached: each agent's first block writes it and
the remaining blocks read it, and every block uses the same output schema (``SurveyBlock``).
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from .. import llm
from ..config import get_settings
from ..models import new_id
from ..storage import get_store
from . import costs
from . import prompts as SP
from .models import SurveyIn
from .runner import StepCtx, batch_loop, new_run
from .sampling import rng_for
from .schemas import make_survey_schema

log = logging.getLogger("undercurrent.sim")

SCHEMA_NAME = "SurveyBlock"


def persona_for(agent: dict, style: str, card_detail: str = "light", geography: str = "") -> str:
    if style == "demographics":
        return SP.demographics_block(agent, geography)
    if style == "card":
        return SP.card_block(agent, geography)
    return SP.persona_block(agent, card_detail, geography)


def _persona_tokens(pop: dict, style: str) -> int:
    if style == "demographics":
        return 120
    if style == "card" or pop.get("persona_mode") == "demographic":
        return 400
    return costs.persona_tokens(pop.get("transcript_words") or 900, pop.get("reflections_per_expert") or 6)


def create_survey(body: SurveyIn) -> dict:
    store = get_store()
    s = get_settings()
    pop = store.get("populations", body.population_id)
    if not pop:
        raise HTTPException(404, "Population not found")
    agents = store.find("agents", sort="index", fields=["index"], population_id=body.population_id, persona_status="ready")
    if not agents:
        raise HTTPException(422, "This population has no ready agents yet.")
    seed = body.seed if body.seed is not None else int(new_id()[:7], 16)
    chosen = agents
    if body.sample_size and body.sample_size < len(agents):
        chosen = sorted(rng_for("survey-sample", seed).sample(agents, body.sample_size), key=lambda a: a["index"])
    if len(chosen) > s.sim_max_agents:
        raise HTTPException(422, f"Surveys are limited to {s.sim_max_agents} agents (SIM_MAX_AGENTS).")
    blocks = [b.model_dump() for b in body.blocks]
    block_size = len(blocks[0]["questions"])
    est = costs.estimate_survey(len(chosen), len(blocks), block_size, _persona_tokens(pop, body.persona_style))
    config = {
        "agent_ids": [a["id"] for a in chosen],
        "blocks": blocks,
        "block_size": block_size,
        "persona_style": body.persona_style,
        "preamble": body.preamble,
        "seed": seed,
        "card_detail": pop.get("card_detail", "light"),
        "geography": pop.get("geography", ""),
    }
    return new_run("survey", body.population_id, body.title, config, len(chosen), est)


def _letter_index(q: dict, letter: str | None) -> int | None:
    if not letter or letter not in SP.SURVEY_LETTERS:
        return None
    i = SP.SURVEY_LETTERS.index(letter)
    return i if i < len(q["options"]) else None


def agent_call(agent: dict, cfg: dict, block: dict, schema: type) -> tuple[dict, dict]:
    s = get_settings()
    persona = persona_for(agent, cfg["persona_style"], cfg.get("card_detail", "light"), cfg.get("geography", ""))
    out, usage = llm.structured(
        SP.survey_task(block["questions"], cfg.get("preamble", "")),
        schema,
        system=SP.AGENT_SYSTEM,
        cache_system=True,
        blocks=[llm.Block(persona, cache=True)],
        effort=s.sim_agent_effort,
        thinking=s.sim_agent_thinking,  # type: ignore[arg-type]
        model=s.sim_model,
        max_tokens=1000 + 40 * len(block["questions"]),
        timeout=s.sim_call_timeout,
        max_retries=1,
        log_level=logging.DEBUG,
    )
    answers = {q["id"]: _letter_index(q, getattr(out, f"a{i}", None)) for i, q in enumerate(block["questions"], 1)}
    return {"answers": answers, "invalid": sum(v is None for v in answers.values())}, usage


def result_id(run_id: str, agent_id: str, block_id: str) -> str:
    return f"{run_id}:{agent_id}:{block_id}"


def step(ctx: StepCtx) -> None:
    store = get_store()
    cfg = ctx.run["config"]
    schema = make_survey_schema(cfg["block_size"], SCHEMA_NAME)
    blocks = cfg["blocks"]
    rid = ctx.run["id"]

    def process(ctx: StepCtx, idx: list[int]) -> None:
        agents = [a for a in (store.get("agents", cfg["agent_ids"][i]) for i in idx) if a]
        # first block per agent writes its persona to the prompt cache; the other blocks read it
        first = [(a, blocks[0]) for a in agents]
        later = [(a, b) for a in agents for b in blocks[1:]]
        docs, failed = [], set()
        for wave in (first, later):
            for (agent, block), value, err in ctx.parallel(lambda item: agent_call(item[0], cfg, item[1], schema), wave):
                docs.append({
                    "id": result_id(rid, agent["id"], block["id"]), "run_id": rid, "agent_id": agent["id"],
                    "block_id": block["id"], "status": "ok" if err is None else "error",
                    "answers": (value or {}).get("answers", {}), "invalid": (value or {}).get("invalid", 0),
                    "error": err.message if err else "",
                })
                if err is not None:
                    failed.add(agent["id"])
        store.upsert_many("sim_results", docs)
        ctx.failed += len(failed)
        ctx.done += len(agents) - len(failed)

    batch_loop(ctx, len(cfg["agent_ids"]), process, len(blocks))


def answers_by_agent(run: dict) -> dict[str, dict[str, int | None]]:
    """{agent_id: {question_id: option index or None}} from the run's saved block results."""
    out: dict[str, dict[str, int | None]] = {}
    for r in get_store().find("sim_results", run_id=run["id"], status="ok"):
        out.setdefault(r["agent_id"], {}).update(r.get("answers") or {})
    return out


def summarize(run: dict) -> dict:
    cfg = run["config"]
    results = get_store().find("sim_results", fields=["agent_id", "status", "invalid"], run_id=run["id"])
    ok = [r for r in results if r.get("status") == "ok"]
    n_q = sum(len(b["questions"]) for b in cfg["blocks"])
    complete = {}
    for r in ok:
        complete[r["agent_id"]] = complete.get(r["agent_id"], 0) + 1
    invalid = sum(int(r.get("invalid") or 0) for r in ok)
    return {
        "n_agents": len(cfg["agent_ids"]),
        "n_complete": sum(1 for v in complete.values() if v == len(cfg["blocks"])),
        "n_block_errors": len(results) - len(ok),
        "n_questions": n_q,
        "invalid_answer_rate": round(invalid / max(1, len(ok) * cfg["block_size"]), 4),
    }


def finalize(ctx: StepCtx) -> None:
    ctx.patch["results"] = summarize(ctx.run)
    ctx.status = "done"


def failed_units(run: dict) -> list[int]:
    ids = run["config"]["agent_ids"]
    bad = {r["agent_id"] for r in get_store().find("sim_results", fields=["agent_id"], run_id=run["id"], status="error")}
    return [i for i, aid in enumerate(ids) if aid in bad]
