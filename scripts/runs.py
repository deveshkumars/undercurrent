"""Helpers shared by the scripts that drive simulation runs in-process."""

from __future__ import annotations

import sys


def drive(runner, store, rid: str) -> dict:
    """Step a run to completion in-process (same lease/step protocol the browser uses)."""
    run = store.get("sim_runs", rid)
    last = None
    while run["status"] not in ("done", "failed", "canceled"):
        if run["status"] in ("paused", "budget_exhausted"):
            sys.exit(f"run {rid} stopped: {run['status']} {run.get('error', '')} {run.get('log', [])[-3:]}")
        run = runner.step(rid)
        p = run["progress"]
        msg = f"  {run['title'][:70]}: {run['cursor']}/{run['total']} · {p['calls']} calls · ${p['usd']:.3f} · {run['status']}"
        if msg != last:
            print(msg, flush=True)
            last = msg
    if run["status"] != "done":
        sys.exit(f"run {rid} ended {run['status']}: {run.get('error')}")
    return run


def wall_minutes(run: dict) -> float:
    """Created-to-last-update time of a run (includes any time it sat paused between invocations)."""
    from datetime import datetime

    t0, t1 = (datetime.fromisoformat(run[k].replace("Z", "+00:00")) for k in ("created_at", "updated_at"))
    return round((t1 - t0).total_seconds() / 60, 1)


def run_record(run: dict) -> dict:
    p = run["progress"]
    return {
        "wall_minutes": wall_minutes(run),
        "id": run["id"], "title": run["title"], "created_at": run["created_at"], "updated_at": run["updated_at"],
        "calls": p["calls"], "failed_units": p.get("failed", 0),
        "input_tokens": p["input_tokens"], "output_tokens": p["output_tokens"],
        "cache_read_input_tokens": p["cache_read_input_tokens"],
        "cache_creation_input_tokens": p["cache_creation_input_tokens"],
        "cache_creation_1h_input_tokens": p.get("cache_creation_1h_input_tokens", 0),
        "usd_list_price": p["usd"], "estimate_usd": run["estimate"]["usd"],
        "results": run.get("results"),
    }
