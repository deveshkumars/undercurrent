"""Built-in demo scenarios: real runs saved by scripts/seed_demos.py and loaded into the store, so the
demos display with no API key. Every document carries ``demo: True``.

Loading is idempotent: documents keep their original ids and are upserted, and a population-level
``demo_version`` marker skips the work once the current fixture is in the store. It happens lazily on
the first simulation request of a process (and can be turned off with SIM_DEMO_FIXTURES=off).
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path

from ..storage import get_store

log = logging.getLogger("undercurrent.sim")

FIXTURE = Path(__file__).parent / "fixtures" / "demo.json.gz"
COLLECTIONS = ("populations", "agents", "sim_runs", "sim_results", "sim_ticks", "sim_posts", "sim_state")
_lock = threading.Lock()
_loaded_for: set[int] = set()


def enabled() -> bool:
    return os.environ.get("SIM_DEMO_FIXTURES", "on").strip().lower() not in ("off", "0", "false", "no")


@lru_cache
def fixture() -> dict | None:
    if not FIXTURE.exists():
        return None
    with gzip.open(FIXTURE, "rt") as f:
        return json.load(f)


def ensure_loaded() -> bool:
    """Put the demo documents in the store if this fixture version isn't there yet. True if anything was written."""
    if not enabled():
        return False
    store = get_store()
    with _lock:
        if id(store) in _loaded_for:
            return False
        data = fixture()
        if not data:
            _loaded_for.add(id(store))
            return False
        pops = data["docs"].get("populations") or []
        current = store.get("populations", pops[0]["id"]) if pops else None
        if current and current.get("demo_version") == data["version"]:
            _loaded_for.add(id(store))
            return False
        for coll in COLLECTIONS:
            docs = [dict(d) for d in data["docs"].get(coll) or []]
            if coll == "populations":
                for d in docs:
                    d["demo_version"] = data["version"]
                continue  # written last, so a crash midway retries the whole load next time
            if docs:
                store.upsert_many(coll, docs)
        store.upsert_many("populations", [dict(d, demo_version=data["version"]) for d in pops])
        _loaded_for.add(id(store))
        log.info("loaded demo fixtures %s", data["version"])
        return True


def demo_ids() -> dict[str, list[str]]:
    """Ids of the demo population and runs, for the home page."""
    data = fixture()
    if not data:
        return {"populations": [], "runs": []}
    return {"populations": [p["id"] for p in data["docs"]["populations"]],
            "runs": [r["id"] for r in data["docs"]["sim_runs"]]}
