"""Generate the two built-in demo scenarios and save them as fixtures, so they display without an API key.

    .venv/bin/python scripts/seed_demos.py --dry-run
    LLM_BACKEND=claude-cli SIM_CONCURRENCY=12 .venv/bin/python scripts/seed_demos.py

1. Product launch message test: a fictional smart thermostat (Brightloop), a control and three message
   variants, product questionnaire, on a 150-agent interview population of U.S. adults.
2. Brand crisis: a fictional kettle recall (Kettlewise) on a simulated social feed, branched two hours
   in into an apology, a transparency response and a no-change control.

All brands, products and people are fictional. Runs go through the normal step protocol in a separate
JSON store (data/demo/db.json, resumable); the finished documents are exported to
backend/app/sim/fixtures/demo.json.gz, which backend/app/sim/demo.py loads at runtime.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shlex
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.runs import drive, run_record  # noqa: E402

OUT = ROOT / "backend" / "app" / "sim" / "fixtures" / "demo.json.gz"
SEED = 7

POPULATION = {
    "name": "Demo audience: U.S. adults",
    "description": "150 synthetic U.S. adults with model-written life-history interviews. Built for the demo scenarios.",
    "size": 150, "preset": "us_adults", "persona_mode": "interview", "card_detail": "light", "seed": SEED,
}

PRODUCT = {
    "title": "Brightloop thermostat: launch message test",
    "subject": "the Brightloop smart thermostat",
    "questionnaire": "product",
    "context": ("Brightloop is a new smart thermostat from Brightloop Home, a small company in Ohio. It costs $129, "
                "installs in about 20 minutes with a screwdriver, and works with most home heating and cooling systems. "
                "It is sold online and at hardware stores."),
    "arms": [
        {"id": "control", "label": "No ad (placebo news)", "kind": "control", "control_mode": "placebo"},
        {"id": "savings", "label": "Savings", "kind": "treatment", "format": "product_description", "source": "an online ad",
         "text": "Your heating bill, minus 18%.\n\nBrightloop learns when you're home and when you're not, and stops paying to "
                 "heat and cool an empty house. Most homes save $90 to $150 a year, so it pays for itself in about a year. "
                 "$129. Installs in 20 minutes. Brightloop: the thermostat that pays you back."},
        {"id": "comfort", "label": "Comfort", "kind": "treatment", "format": "product_description", "source": "an online ad",
         "text": "Come home to exactly 70 degrees.\n\nBrightloop warms the house before your alarm goes off and cools it before "
                 "you pull into the driveway. No more fighting over the dial, no more cold bathroom floors. Set it once from "
                 "your phone and forget it. $129. Brightloop: comfort that thinks ahead."},
        {"id": "climate", "label": "Climate", "kind": "treatment", "format": "product_description", "source": "an online ad",
         "text": "Heating and cooling are about half of a home's energy use.\n\nBrightloop cuts the waste automatically, so the "
                 "average home avoids about a ton of carbon emissions a year, the same as not driving 2,500 miles. It even "
                 "shifts heating to hours when the grid runs cleaner. $129. Brightloop: a smaller footprint, without trying."},
    ],
}

SEED_EVENT = ("BREAKING: Kettlewise is recalling 1.2 million StillPour electric kettles sold since March after reports that the "
              "base can overheat and melt. The company says 37 people reported minor burns and no one was seriously hurt. "
              "Customers are told to stop using the kettles immediately.")
APOLOGY = ("We're sorry. Our StillPour kettles let you down, and some of you got hurt. Please stop using yours today. We'll "
           "send every owner a prepaid return box and a full refund or a free replacement, your choice. We've stopped "
           "production until an independent lab signs off on the fix. This is on us, and we'll keep you updated here.")
TRANSPARENCY_1 = ("Here is what we know right now. A solder joint in the base of StillPour kettles made between March and August "
                  "can overheat. We've had 37 reports of minor burns. Check whether your kettle is affected with the serial "
                  "number on the bottom; if it starts with SP03 to SP08, stop using it. We'll post the full engineering report "
                  "and a timeline of when we learned about this by tonight.")
TRANSPARENCY_2 = ("Full update, as promised. The independent lab's report is attached. Timeline: we received the first overheating "
                  "complaint on June 3, confirmed the defect on September 12, and notified regulators on September 19, a week "
                  "later than we should have. Refunds and replacements start Monday; you can choose either.")

SOCIAL = {
    "title": "Kettlewise recall: how it spreads",
    "focal_subject": "Kettlewise",
    "context": "Kettlewise is a mid-sized American kitchen-appliance brand known for affordable kettles and toasters.",
    "n_agents": 80, "duration_hours": 12, "tick_minutes": 10, "max_calls_per_tick": 12, "start_clock": "08:00",
    "seed_event": {"at_minute": 0, "kind": "event", "label": "Recall news",
                   "event": {"author": "media_center", "text": SEED_EVENT, "importance": 2.0, "topics": ["recall", "kettlewise"]}},
    "seed": SEED,
}
BRANCH_TICK = 12  # two hours in


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(ROOT / "data" / "demo" / "db.json"))
    ap.add_argument("--max-usd", type=float, default=5.0)
    args = ap.parse_args()
    os.environ["DATA_FILE"] = args.db
    os.environ["MONGODB_URI"] = ""  # always the local JSON store above, even if .env points at a real database
    os.environ.setdefault("SIM_STEP_SECONDS", "900")
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    from backend.app.config import get_settings
    from backend.app.sim import costs, jobs, panel, runner, social
    from backend.app.sim.models import BranchIn, Intervention, PanelIn, PopulationIn, SocialIn
    from backend.app.storage import get_store

    s = get_settings()
    store = get_store()
    persona_tok = costs.persona_tokens(900, 6)
    est = {
        "population (150 interview personas)": costs.estimate_populate(150, "interview"),
        "product message test (150 agents x 4 arms)": costs.estimate_panel(150, 4, 1, 7, persona_tok, 120),
        "social base run (80 agents, 12 h)": costs.estimate_social(80, 12, 10, 12),
        "social branches (3 x 10 h)": {k: v * 3 if isinstance(v, (int, float)) else v
                                       for k, v in costs.estimate_social(80, 10, 10, 12).items()},
    }
    print(f"Estimate (model {s.sim_model} via {s.llm_backend}; API-equivalent cost, i.e. Anthropic API list price for the same tokens):")
    for k, e in est.items():
        print(f"  {k:44s} {e['calls']:>6,} calls  ${e['usd']:.2f}")
    print(f"  total ${sum(e['usd'] for e in est.values()):.2f}")
    if any(e["usd"] > args.max_usd for e in est.values()):
        sys.exit(f"A run is estimated above ${args.max_usd}.")
    if args.dry_run:
        return

    pop = next(iter(store.find("populations", name=POPULATION["name"])), None)
    if not pop:
        pop = jobs.create_synthetic(PopulationIn(**POPULATION))
    if pop.get("populate_run_id"):
        drive(runner, store, pop["populate_run_id"])
    pop = store.get("populations", pop["id"])

    prod = next(iter(store.find("sim_runs", kind="panel", title=PRODUCT["title"])), None)
    if not prod:
        prod = panel.create_panel(PanelIn(population_id=pop["id"], seed=SEED, **PRODUCT))
    prod = drive(runner, store, prod["id"])

    base = next(iter(store.find("sim_runs", kind="social", title=SOCIAL["title"])), None)
    if not base:
        base = social.create_social(SocialIn(population_id=pop["id"], **SOCIAL))
    base = drive(runner, store, base["id"])
    branches = store.find("sim_runs", kind="social", parent_run_id=base["id"])
    if not branches:
        at = BRANCH_TICK * SOCIAL["tick_minutes"]
        ev = lambda text, minute, imp=1.0: Intervention(at_minute=minute, kind="event", label="",  # noqa: E731
                                                       event={"author": "official", "text": text, "importance": imp, "topics": []})
        apology = ev(APOLOGY, at)
        apology.label = "Apology"
        t1, t2 = ev(TRANSPARENCY_1, at), ev(TRANSPARENCY_2, at + 360, 0.8)
        t1.label = t2.label = "Transparency"
        branches = social.branch(base, BranchIn(tick=BRANCH_TICK, title="Apology at 10:00", interventions=[apology], with_control=True))
        branches += social.branch(base, BranchIn(tick=BRANCH_TICK, title="Transparency at 10:00 (facts now, full report at 16:00)",
                                                 interventions=[t1, t2], with_control=False))
    branches = [drive(runner, store, b["id"]) for b in branches]

    export(store, pop, [prod, base, *branches], s)


def export(store, pop: dict, runs: list[dict], s) -> None:
    run_ids = {r["id"] for r in runs} | ({pop["populate_run_id"]} if pop.get("populate_run_id") else set())
    docs: dict[str, list[dict]] = {
        "populations": [pop],
        "agents": store.find("agents", population_id=pop["id"]),
        "sim_runs": [store.get("sim_runs", rid) for rid in sorted(run_ids)],
        "sim_results": [d for rid in sorted(run_ids) for d in store.find("sim_results", run_id=rid)],
        "sim_ticks": [d for rid in sorted(run_ids) for d in store.find("sim_ticks", run_id=rid)],
        "sim_posts": [d for rid in sorted(run_ids) for d in store.find("sim_posts", run_id=rid)],
        "sim_state": [d for rid in sorted(run_ids) if (d := store.get("sim_state", rid))],
    }
    for coll in docs.values():
        for d in coll:
            d["demo"] = True
    for r in docs["sim_runs"]:
        r["lease_owner"], r["lease_expires_at"] = None, 0.0
    body = json.dumps(docs, sort_keys=True)
    version = hashlib.sha256(body.encode()).hexdigest()[:12]
    payload = {
        "version": version,
        "generated": {
            "date": date.today().isoformat(),
            "command": f"LLM_BACKEND={s.llm_backend} .venv/bin/python scripts/seed_demos.py " + " ".join(shlex.quote(a) for a in sys.argv[1:]),
            "model": s.sim_model, "backend": s.llm_backend,
            "runs": [run_record(r) for r in docs["sim_runs"]],
        },
        "docs": docs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", compresslevel=9) as f:
        json.dump(payload, f, separators=(",", ":"))
    counts = {k: len(v) for k, v in docs.items()}
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, version {version}): {counts}")


if __name__ == "__main__":
    main()
