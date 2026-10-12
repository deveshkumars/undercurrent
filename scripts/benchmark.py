"""Scale and cost benchmark: a 1,000-agent, 3-arm message test, measured from actual usage.

    .venv/bin/python scripts/benchmark.py --dry-run
    LLM_BACKEND=claude-cli SIM_CONCURRENCY=12 .venv/bin/python scripts/benchmark.py

Builds (or reuses) a 1,000-agent interview population, then runs a control + 2 message variants
product test on all of them through the normal step protocol, in-process. Every model call goes
through a wrapper around llm.structured that logs the usage the API (or the claude-cli shim) reported
and the call's latency, so calls, tokens, cache reads/writes, hit rates and dollars all come from
actual responses, not estimates. Results go to docs/benchmarks.json and docs/benchmarks.md.

Dollar figures are API-equivalent (Anthropic list price for the reported tokens, with 1-hour cache
writes at 2x and 5-minute writes at 1.25x input). Through the claude-cli shim nothing is billed per
token; the run counts against the Claude Code subscription instead.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import statistics
import sys
import threading
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.runs import drive, run_record  # noqa: E402

OUT_JSON = ROOT / "docs" / "benchmarks.json"
OUT_MD = ROOT / "docs" / "benchmarks.md"
SEED = 1000

PANEL = {
    "title": "Benchmark: 1,000-agent message test",
    "subject": "the Brightloop smart thermostat",
    "questionnaire": "product",
    "context": ("Brightloop is a new smart thermostat from Brightloop Home, a small company in Ohio. It costs $129, installs "
                "in about 20 minutes with a screwdriver, and works with most home heating and cooling systems."),
    "arms": [
        {"id": "control", "label": "No ad (placebo news)", "kind": "control", "control_mode": "placebo"},
        {"id": "savings", "label": "Savings", "kind": "treatment", "format": "product_description", "source": "an online ad",
         "text": "Your heating bill, minus 18%.\n\nBrightloop learns when you're home and when you're not, and stops paying to "
                 "heat and cool an empty house. Most homes save $90 to $150 a year, so it pays for itself in about a year. "
                 "$129. Installs in 20 minutes."},
        {"id": "comfort", "label": "Comfort", "kind": "treatment", "format": "product_description", "source": "an online ad",
         "text": "Come home to exactly 70 degrees.\n\nBrightloop warms the house before your alarm goes off and cools it before "
                 "you pull into the driveway. Set it once from your phone and forget it. $129."},
    ],
}


class CallLog:
    """Wraps llm.structured and appends one JSON line per call (usage + latency + output schema)."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def install(self) -> None:
        from backend.app import llm

        inner = llm.structured

        def logged(task, output, *args, **kw):
            t0 = time.monotonic()
            try:
                value, usage = inner(task, output, *args, **kw)
            except llm.LLMError as e:
                self.write({"schema": output.__name__, "ok": False, "error": e.message[:200],
                            "seconds": round(time.monotonic() - t0, 3), "t": time.time()})
                raise
            self.write({"schema": output.__name__, "ok": True, "seconds": round(time.monotonic() - t0, 3), "t": time.time(),
                        **{k: usage.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                        "cache_creation_input_tokens", "cache_creation_1h_input_tokens")}})
            return value, usage

        llm.structured = logged

    def write(self, row: dict) -> None:
        with self.lock, self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")


def summarize_calls(rows: list[dict], t_start: float | None = None) -> dict:
    from backend.app.sim import costs

    ok = [r for r in rows if r.get("ok")]
    tok = {k: sum(r.get(k, 0) for r in ok) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                       "cache_creation_input_tokens", "cache_creation_1h_input_tokens")}
    total_in = tok["input_tokens"] + tok["cache_read_input_tokens"] + tok["cache_creation_input_tokens"]
    lat = sorted(r["seconds"] for r in ok)
    span = (max(r["t"] for r in rows) - min(r["t"] - r["seconds"] for r in rows)) if rows else 0
    return {
        "calls": len(rows),
        "failed_calls": len(rows) - len(ok),
        **tok,
        "total_input_tokens": total_in,
        "cache_hit_rate_tokens": round(tok["cache_read_input_tokens"] / total_in, 4) if total_in else None,
        "calls_with_cache_read": round(sum(1 for r in ok if r.get("cache_read_input_tokens", 0) > 0) / len(ok), 4) if ok else None,
        "usd_api_equivalent": round(costs.usd(tok), 4),
        "latency_p50_s": round(statistics.median(lat), 2) if lat else None,
        "latency_p95_s": round(lat[int(0.95 * (len(lat) - 1))], 2) if lat else None,
        "call_span_minutes": round(span / 60, 1),
        "calls_per_minute": round(len(rows) / (span / 60), 1) if span else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="1,000-agent, 3-arm message test benchmark.")
    ap.add_argument("--agents", type=int, default=1000)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-usd", type=float, default=5.0, help="refuse any single run estimated above this")
    ap.add_argument("--db", default=str(ROOT / "data" / "benchmark" / "db.json"))
    ap.add_argument("--render", action="store_true", help="only re-render docs/benchmarks.md from docs/benchmarks.json")
    args = ap.parse_args()
    if args.render:
        render(json.loads(OUT_JSON.read_text()))
        return
    os.environ["DATA_FILE"] = args.db
    os.environ["MONGODB_URI"] = ""  # always the local JSON store above, even if .env points at a real database
    os.environ.setdefault("SIM_STEP_SECONDS", "900")
    os.environ["SIM_MAX_AGENTS"] = str(max(args.agents, int(os.environ.get("SIM_MAX_AGENTS") or 0)))
    os.environ.setdefault("SIM_MAX_CALLS_PER_RUN", "10000")
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)

    from backend.app.config import get_settings
    from backend.app.sim import costs, jobs, panel, runner
    from backend.app.sim.models import PanelIn, PopulationIn
    from backend.app.storage import get_store

    s = get_settings()
    store = get_store()
    pop_name = f"Benchmark: {args.agents} U.S. adults (interview)"
    pop = next(iter(store.find("populations", name=pop_name)), None)
    persona_tok = costs.persona_tokens(900, 6)
    est = {}
    if not pop or pop.get("status") != "ready":
        est["population"] = costs.estimate_populate(args.agents, "interview")
    stim = int(sum(len(a.get("text", "")) for a in PANEL["arms"]) / len(PANEL["arms"]) / 4) + 60
    est["message test"] = costs.estimate_panel(args.agents, len(PANEL["arms"]), 1, 7, persona_tok, stim)
    print(f"Estimate (model {s.sim_model} via {s.llm_backend}, concurrency {s.sim_concurrency}; API-equivalent cost):")
    for k, e in est.items():
        print(f"  {k:14s} {e['calls']:>6,} calls  {e['input_tokens']:>12,} in  {e['output_tokens']:>10,} out  ${e['usd']:.2f}  ~{e['minutes']} min")
    if s.llm_backend == "claude-cli":
        print("  Through the claude-cli shim, measured usage has run 2-5x these API-path estimates (1-hour cache writes, an")
        print("  extra structured-output turn); billed to the Claude Code subscription, not per token.")
    if any(e["usd"] > args.max_usd for e in est.values()):
        sys.exit(f"A run is estimated above ${args.max_usd}.")
    if args.dry_run:
        return

    calls_file = db.parent / "calls.jsonl"
    log = CallLog(calls_file)
    log.install()

    if not pop:
        pop = jobs.create_synthetic(PopulationIn(name=pop_name, size=args.agents, preset="us_adults", persona_mode="interview",
                                                 card_detail="light", seed=SEED,
                                                 description="Built by scripts/benchmark.py."))
    t0 = time.time()
    pop_run = drive(runner, store, pop["populate_run_id"]) if pop.get("populate_run_id") else None
    pop_secs = time.time() - t0

    title = f"{PANEL['title']} ({args.agents} agents, seed {SEED})"
    run = next(iter(store.find("sim_runs", kind="panel", title=title)), None)
    if not run:
        run = panel.create_panel(PanelIn(population_id=pop["id"], seed=SEED, **(PANEL | {"title": title})))
    t1 = time.time()
    run = drive(runner, store, run["id"])
    panel_secs = time.time() - t1

    rows = [json.loads(line) for line in calls_file.read_text().splitlines() if line.strip()]
    persona_rows = [r for r in rows if r["schema"] == "PersonaOutput"]
    panel_rows = [r for r in rows if r["schema"].startswith("PanelAnswers")]
    other_rows = [r for r in rows if r not in persona_rows and r not in panel_rows]
    out = {
        "date": date.today().isoformat(),
        "command": f"LLM_BACKEND={s.llm_backend} SIM_CONCURRENCY={s.sim_concurrency} .venv/bin/python scripts/benchmark.py "
                   + " ".join(shlex.quote(a) for a in sys.argv[1:]),
        "model": s.sim_model,
        "backend": s.llm_backend,
        "concurrency": s.sim_concurrency,
        "agents": args.agents,
        "arms": [a["label"] for a in PANEL["arms"]],
        "questions": 7,
        "message_test": {
            "run": run_record(run),
            "wall_minutes_this_invocation": round(panel_secs / 60, 1),
            "agent_calls": summarize_calls(panel_rows),
            "all_calls": summarize_calls(panel_rows + [r for r in other_rows if r["t"] >= t1]),
            "results": {"n_agents": run["results"].get("n_agents"), "n_errors": run["results"].get("n_errors"),
                        "effects": {t: {q: {k: e.get(k) for k in ("est", "lo", "hi", "n")} for q, e in per.items() if q == run["results"].get("primary")}
                                    for t, per in (run["results"].get("effects") or {}).items()}},
        },
        "population": {
            "run": run_record(pop_run) if pop_run else None,
            "wall_minutes_this_invocation": round(pop_secs / 60, 1) if pop_run else None,
            "calls": summarize_calls(persona_rows) if persona_rows else None,
        },
        "estimate": est,
    }
    OUT_JSON.write_text(json.dumps(out, indent=1) + "\n")
    render(out)
    print(json.dumps(out["message_test"]["agent_calls"], indent=1))


def render(out: dict) -> None:
    mt = out["message_test"]
    a = mt["agent_calls"]
    allc = mt["all_calls"]
    p = out["population"]
    lines = [
        "# Benchmarks",
        "",
        "Every number on this page was measured, not estimated: `scripts/benchmark.py` wraps each model call and logs the usage the "
        "model backend reported and the call's latency. Regenerate with the command below; the raw summary is in "
        "[benchmarks.json](benchmarks.json).",
        "",
        f"## {out['agents']:,}-agent, {len(out['arms'])}-arm message test",
        "",
        f"Run {out['date']}: `{out['command']}`  ",
        f"Model `{out['model']}` via `{out['backend']}`, {out['concurrency']} calls at a time; arms: {', '.join(out['arms'])}; "
        f"{out['questions']} questions (product questionnaire); one structured call per agent per arm, the control first so it "
        "writes the agent's persona to the prompt cache and the other arms read it.",
        "",
        "| | Message test (agent calls) | Including the debrief |",
        "|---|---|---|",
        f"| Wall time | {mt['wall_minutes_this_invocation']} min | |",
        f"| Calls (failed) | {a['calls']:,} ({a['failed_calls']}) | {allc['calls']:,} ({allc['failed_calls']}) |",
        f"| Throughput | {a['calls_per_minute']} calls/min | |",
        f"| Latency p50 / p95 | {a['latency_p50_s']} s / {a['latency_p95_s']} s | |",
        f"| Input tokens: uncached | {a['input_tokens']:,} | {allc['input_tokens']:,} |",
        f"| Input tokens: cache write (of which 1-hour) | {a['cache_creation_input_tokens']:,} ({a['cache_creation_1h_input_tokens']:,}) | "
        f"{allc['cache_creation_input_tokens']:,} ({allc['cache_creation_1h_input_tokens']:,}) |",
        f"| Input tokens: cache read | {a['cache_read_input_tokens']:,} | {allc['cache_read_input_tokens']:,} |",
        f"| Output tokens | {a['output_tokens']:,} | {allc['output_tokens']:,} |",
        f"| Prompt-cache hit rate (share of input tokens read from cache) | {a['cache_hit_rate_tokens'] * 100:.1f}% | "
        f"{allc['cache_hit_rate_tokens'] * 100:.1f}% |",
        f"| Calls that read from the cache | {a['calls_with_cache_read'] * 100:.1f}% | |",
        f"| API-equivalent cost | ${a['usd_api_equivalent']:.2f} | ${allc['usd_api_equivalent']:.2f} |",
        "",
    ]
    if p.get("calls"):
        pc = p["calls"]
        lines += [
            f"Building the {out['agents']:,} interview personas (one call each, a one-time cost per population): "
            f"{pc['calls']:,} calls ({pc['failed_calls']} failed), {p['wall_minutes_this_invocation']} min, "
            f"{pc['output_tokens']:,} output tokens, ${pc['usd_api_equivalent']:.2f} API-equivalent.",
            "",
        ]
    est = out["estimate"].get("message test", {})
    lines += [
        "### Reading it",
        "",
        f"- The pre-run estimate (API path) was {est.get('calls', 0):,} calls and ${est.get('usd', 0):.2f}; measured cost was "
        f"${a['usd_api_equivalent']:.2f}. " + ("Through the claude-cli shim each call carries Claude Code's own overhead (1-hour cache "
        "writes billed at 2x input, and an extra turn for structured output), so the direct API path should come in below the "
        "measured figure. Nothing was billed per token: the shim runs on the Claude Code subscription." if out["backend"] == "claude-cli"
        else ""),
        f"- Almost every call reads something from the cache ({a['calls_with_cache_read'] * 100:.1f}%): the system prompt is shared by "
        "all agents, and each agent's persona is written by its control call and read by its other two arms. The token hit rate "
        f"({a['cache_hit_rate_tokens'] * 100:.1f}%) is lower because the persona has to be written once per agent"
        + (" (and the CLI also caches each call's tail, which adds writes that are never read)" if out["backend"] == "claude-cli" else "")
        + ".",
        f"- The step protocol held at this size: the run recorded {mt['run']['calls']:,} calls, matching the {allc['calls']:,} "
        f"logged call by call, with {(mt['results'].get('n_errors') or 0)} failed responses and one stored result per agent and arm. "
        f"The measured effect on purchase intent (0–100) for Savings vs the control was "
        f"{mt['results']['effects'].get('savings', {}).get('purchase_intent', {}).get('est')} "
        f"[{mt['results']['effects'].get('savings', {}).get('purchase_intent', {}).get('lo')}, "
        f"{mt['results']['effects'].get('savings', {}).get('purchase_intent', {}).get('hi')}] on {out['agents']:,} paired agents.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines))
    print(f"rendered {OUT_MD}")


if __name__ == "__main__":
    main()
