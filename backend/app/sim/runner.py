"""Client-driven run execution.

The browser calls POST /api/sim/runs/{id}/step in a loop. Each step:
1. claims a lease with a compare-and-set on ``version`` (a second caller gets 409 and just watches),
2. runs batches of work on a thread pool until the step's time budget is spent,
3. upserts results under deterministic ids (re-running a chunk overwrites, never duplicates), and only
   while it still holds the lease (``StepCtx.save``),
4. releases the lease while advancing the cursor and the usage counters.

A step that outlives its lease (e.g. a hung model call) can be taken over by another caller, which
redoes the unfinished units. The late step then discards its results instead of overwriting newer
ones, stops, and still adds the calls and tokens it spent to the run's usage, so cost is never lost.

This needs no background worker, so it runs the same locally and on a 300-second serverless function.
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from fastapi import HTTPException

from .. import llm
from ..config import get_settings
from ..models import new_id, utcnow
from ..storage import get_store
from . import costs

log = logging.getLogger("undercurrent.sim")

TERMINAL = {"done", "failed", "canceled"}
HANDLER_MODULES = {
    "populate": "backend.app.sim.jobs",
    "panel": "backend.app.sim.panel",
    "calibration": "backend.app.sim.panel",
    "backtest": "backend.app.sim.candidate",
    "social": "backend.app.sim.social",
    "survey": "backend.app.sim.survey",
}
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
              "cache_creation_1h_input_tokens")


def new_run(
    kind: str, population_id: str, title: str, config: dict, total: int, estimate: dict,
    candidate_id: str | None = None, parent_run_id: str | None = None, **extra: Any,
) -> dict:
    s = get_settings()
    now = utcnow()
    max_calls = min(s.sim_max_calls_per_run, max(10, int(estimate.get("calls", 0) * 1.25) + 5))
    run = {
        "id": new_id(),
        "kind": kind,
        "population_id": population_id,
        "candidate_id": candidate_id,
        "parent_run_id": parent_run_id,
        "title": title,
        "config": config,
        "created_at": now,
        "updated_at": now,
        "status": "pending",
        "cursor": 0,
        "total": total,
        "retry": [],
        "version": 0,
        "lease_owner": None,
        "lease_expires_at": 0.0,
        "concurrency": s.sim_concurrency,
        "progress": {"done": 0, "failed": 0, "calls": 0, "usd": 0.0, "avg_batch_s": None, **{k: 0 for k in USAGE_KEYS}},
        "estimate": estimate,
        "budget": {"max_calls": max_calls},
        "log": [],
        "error": "",
        "results": {},
        "model": s.sim_model,
    }
    run.update(extra)
    get_store().insert("sim_runs", run)
    return run


class StepCtx:
    """Shared state for one step: deadline, concurrency, budget and usage accounting."""

    def __init__(self, run: dict, token: str):
        s = get_settings()
        self.run = run
        self.token = token
        self.started = time.monotonic()
        self.step_seconds = s.sim_step_seconds
        self.concurrency = max(1, min(int(run.get("concurrency") or s.sim_concurrency), s.sim_concurrency))
        self.cursor: int = run["cursor"]
        self.retry: list[int] = list(run.get("retry") or [])
        self.patch: dict[str, Any] = {}
        self.status: str | None = None  # set on a real transition (finalizing, done, budget_exhausted, failed)
        self.usage = {k: 0 for k in USAGE_KEYS}
        self.calls = 0
        self.failed = 0
        self.done = 0
        self.retryable_errors = 0
        self.batch_times: list[float] = []
        self.messages: list[str] = []
        self.fatal: llm.LLMError | None = None
        self.lost_lease = False
        self._lock = threading.Lock()

    # ---- time & budget
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def time_left(self) -> float:
        return self.step_seconds - self.elapsed()

    def avg_batch(self) -> float:
        if self.batch_times:
            return sum(self.batch_times) / len(self.batch_times)
        return float(self.run.get("progress", {}).get("avg_batch_s") or 0.0)

    def should_continue(self) -> bool:
        if self.fatal is not None:
            return False
        if not self.batch_times:
            return True  # always do at least one batch per step
        return self.time_left() > self.avg_batch() * 1.15

    def budget_ok(self, planned_calls: int) -> bool:
        used = self.run["progress"].get("calls", 0) + self.calls
        return used + planned_calls <= self.run["budget"]["max_calls"]

    def canceled(self) -> bool:
        current = get_store().get("sim_runs", self.run["id"])
        return bool(current and current["status"] in ("canceled", "paused"))

    def holds_lease(self) -> bool:
        current = get_store().get("sim_runs", self.run["id"]) or {}
        return current.get("lease_owner") == self.token

    def save(self, coll: str, docs: list[dict]) -> bool:
        """Upsert results only while this step still holds the run's lease. After a takeover the new
        holder redoes these units, so a late step drops its results (and stops) rather than overwrite
        newer ones. Leases outlast a step by two call timeouts plus 30 s, so this is a rare path."""
        if not docs:
            return True
        if not self.holds_lease():
            self.lost_lease = True
            return False
        get_store().upsert_many(coll, docs)
        return True

    def note(self, msg: str) -> None:
        self.messages.append(f"{utcnow()[11:19]} {msg}")

    # ---- calls
    def add_usage(self, usage: dict) -> None:
        with self._lock:
            self.calls += 1
            for k in USAGE_KEYS:
                self.usage[k] += int(usage.get(k) or 0)

    def parallel(self, fn: Callable[[Any], tuple[Any, dict]], items: list[Any]) -> list[tuple[Any, Any, llm.LLMError | None]]:
        """Run fn over items concurrently. fn returns (value, usage) or raises LLMError.

        Returns [(item, value or None, error or None)] in input order."""
        if not items:
            return []

        def wrapped(item: Any) -> tuple[Any, Any, llm.LLMError | None]:
            try:
                value, usage = fn(item)
                self.add_usage(usage)
                return item, value, None
            except llm.LLMError as e:
                return item, None, e
            except Exception as e:  # unexpected bug in our code: record it, keep the run alive
                log.exception("simulation unit failed")
                return item, None, llm.LLMError(f"Internal error: {type(e).__name__}: {e}", 500)

        with ThreadPoolExecutor(max_workers=min(self.concurrency, len(items))) as pool:
            out = list(pool.map(wrapped, items))
        for _, _, err in out:
            if err is None:
                continue
            self.calls += 1
            if err.retryable:
                self.retryable_errors += 1
            if err.status_code in (401, 503) and not err.retryable:
                self.fatal = err  # bad key / backend unreachable config: stop and tell the user
        return out


def _handler(kind: str):
    return importlib.import_module(HANDLER_MODULES[kind])


def claim(rid: str) -> tuple[dict, str]:
    store = get_store()
    run = store.get("sim_runs", rid)
    if not run:
        raise HTTPException(404, "Run not found")
    if run["status"] in TERMINAL or run["status"] in ("paused", "budget_exhausted"):
        raise HTTPException(409, f"Run is {run['status']}.")
    now = time.time()
    if run.get("lease_owner") and run.get("lease_expires_at", 0) > now:
        raise HTTPException(409, "This run is being stepped by another tab or request.")
    s = get_settings()
    token = new_id()
    lease = s.sim_step_seconds + s.sim_call_timeout * 2 + 30
    claimed = store.update_if(
        "sim_runs", rid, {"version": run["version"]},
        {
            "version": run["version"] + 1,
            "lease_owner": token,
            "lease_expires_at": now + lease,
            "status": "running" if run["status"] == "pending" else run["status"],
        },
    )
    if not claimed:
        raise HTTPException(409, "This run is being stepped by another tab or request.")
    return claimed, token


def step(rid: str) -> dict:
    run, token = claim(rid)
    ctx = StepCtx(run, token)
    try:
        mod = _handler(run["kind"])
        if run["status"] == "finalizing":
            mod.finalize(ctx)
            if ctx.status is None:
                ctx.status = "done"
        else:
            mod.step(ctx)
    except llm.LLMError as e:
        ctx.fatal = e
    except HTTPException:
        raise
    except Exception as e:  # keep the lease from dangling; surface the bug on the run
        log.exception("simulation step crashed")
        ctx.status = "failed"
        ctx.patch["error"] = f"{type(e).__name__}: {e}"
    finally:
        out = release(ctx)
    return out


def _with_spend(prog: dict, ctx: StepCtx, run: dict) -> dict:
    prog = dict(prog or {})
    for k in USAGE_KEYS:
        prog[k] = int(prog.get(k) or 0) + ctx.usage[k]
    prog["calls"] = int(prog.get("calls") or 0) + ctx.calls
    prog["usd"] = round(float(prog.get("usd") or 0) + costs.usd(ctx.usage, run.get("model")), 5)
    return prog


def _record_orphan_spend(ctx: StepCtx) -> dict | None:
    """A step that lost its lease adds only what it spent (calls, tokens, dollars); its results were
    discarded and the new lease holder owns progress, the cursor and the status."""
    store = get_store()
    note = (f"{utcnow()[11:19]} A step outlived its lease and was taken over; its {ctx.calls} calls are counted "
            "but its results were discarded.")
    for _ in range(20):
        cur = store.get("sim_runs", ctx.run["id"])
        if not cur:
            return None
        patch = {"progress": _with_spend(cur.get("progress") or {}, ctx, cur), "version": cur["version"] + 1,
                 "log": (list(cur.get("log") or []) + [note])[-30:]}
        done = store.update_if("sim_runs", cur["id"], {"version": cur["version"]}, patch)
        if done:
            return done
    log.error("could not record the spend of an orphaned step on run %s", ctx.run["id"])
    return store.get("sim_runs", ctx.run["id"])


def release(ctx: StepCtx) -> dict:
    store = get_store()
    run = ctx.run
    s = get_settings()
    conc = ctx.concurrency
    if ctx.retryable_errors:
        conc = max(1, conc // 2)
        ctx.note(f"Backend pushed back ({ctx.retryable_errors} retryable errors); concurrency now {conc}.")
    elif ctx.batch_times:
        conc = min(s.sim_concurrency, conc + 2)
    if ctx.fatal is not None:
        ctx.note(f"Stopped: {ctx.fatal.message}")
        if ctx.status is None:
            ctx.status = "paused"

    # compare-and-set on the version too, so spend recorded by an orphaned step in between isn't overwritten
    for _ in range(20):
        current = store.get("sim_runs", run["id"]) or {}
        if current.get("lease_owner") != ctx.token:
            return _record_orphan_spend(ctx) or run  # taken over after the lease expired
        prog = _with_spend(current.get("progress") or {}, ctx, run)
        prog["failed"] = int(prog.get("failed") or 0) + ctx.failed
        prog["done"] = int(prog.get("done") or 0) + ctx.done
        if ctx.batch_times:
            prog["avg_batch_s"] = round(sum(ctx.batch_times) / len(ctx.batch_times), 2)
        patch = dict(ctx.patch)
        patch.update({
            "cursor": ctx.cursor,
            "retry": ctx.retry,
            "progress": prog,
            "concurrency": conc,
            "lease_owner": None,
            "lease_expires_at": 0.0,
            "version": current["version"] + 1,
            "updated_at": utcnow(),
        })
        if ctx.fatal is not None:
            patch["error"] = ctx.fatal.message
        if ctx.messages:
            patch["log"] = (list(current.get("log") or []) + ctx.messages)[-30:]
        if ctx.status and current.get("status") not in ("canceled",):
            patch["status"] = ctx.status
        released = store.update_if("sim_runs", run["id"], {"lease_owner": ctx.token, "version": current["version"]}, patch)
        if released is not None:
            return released
    raise RuntimeError(f"could not release the lease on run {run['id']}")


# ---------------------------------------------------------------- shared batch loop


def batch_loop(ctx: StepCtx, total: int, process: Callable[[StepCtx, list[int]], None], calls_per_unit: int) -> None:
    """Process unit indices (retry queue first, then from the cursor) in batches of ``concurrency``."""
    while ctx.should_continue():
        if ctx.retry:
            idx = ctx.retry[: ctx.concurrency]
            from_retry = True
        elif ctx.cursor < total:
            idx = list(range(ctx.cursor, min(total, ctx.cursor + ctx.concurrency)))
            from_retry = False
        else:
            break
        if not ctx.budget_ok(len(idx) * calls_per_unit):
            ctx.status = "budget_exhausted"
            ctx.note("Stopped at the call budget. Raise it to continue.")
            return
        if ctx.batch_times and ctx.canceled():
            return
        t0 = time.monotonic()
        process(ctx, idx)
        if ctx.lost_lease:
            return  # taken over: the new lease holder redoes these units
        ctx.batch_times.append(time.monotonic() - t0)
        if from_retry:
            ctx.retry = ctx.retry[len(idx):]
        else:
            ctx.cursor += len(idx)
    if ctx.cursor >= total and not ctx.retry and ctx.status is None and ctx.fatal is None:
        ctx.status = "finalizing"
