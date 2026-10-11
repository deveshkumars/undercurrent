"""Replicate classic survey experiments as paired message tests and compare with published effects.

    .venv/bin/python scripts/experiments.py --dry-run
    LLM_BACKEND=claude-cli SIM_CONCURRENCY=12 .venv/bin/python scripts/experiments.py

Each experiment is one panel run on the validation population (scripts/validate.py builds it): a
no-message control arm (required by panels, unused here) and one arm per condition. Every agent
answers under every condition in separate, stateless calls, so conditions are compared on the same
simulated people. The vignettes are textbook items a model has likely read about, so each famous
one also runs as a paraphrase with new numbers and setting, which a memorized answer wouldn't cover.

Reference numbers: Many Labs 1 (Klein et al. 2014, Social Psychology 45(3); supplement
https://osf.io/y36m8/, US and international samples pooled) and the original studies. ML1's d for
anchoring is computed on rank-transformed estimates; this script reports both raw means and a
rank-based d. ML1's published d for allowed/forbidden (1.96) compares raw "yes" rates, which counts
the wording reversal itself; here both arms are scored on the anti-speech answer (No to allow, Yes
to forbid), the like-for-like comparison.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.runs import drive, run_record  # noqa: E402

FIXTURE = ROOT / "backend" / "app" / "sim" / "fixtures" / "experiments.json"
INTRO = "A survey you're taking asks you to imagine the following.\n\n"

DISEASE = ("Imagine that the United States is preparing for the outbreak of an unusual disease, which is expected to kill "
           "600 people. Two alternative programs to fight the disease have been proposed. Assume that the exact scientific "
           "estimate of the consequences of the programs are as follows:\n\n")
SPILL = ("A chemical leak from a rail car is spreading toward a town of 900 residents who can't all be evacuated in time. "
         "Emergency managers have two response plans. Experts' best estimates of the outcomes are:\n\n")
FOOTBALL = ("Imagine that your favorite football team is playing an important game. You have a ticket to the game that you "
            "{how}. However, on the day of the game, it happens to be freezing cold. What do you do?")
CONCERT = ("You have a ticket to see a band you like play an outdoor show tonight. You {how}. An hour before the show it "
           "starts pouring rain and is forecast to keep raining all night.")

EXPERIMENTS = [
    {
        "id": "framing", "label": "Gain vs. loss framing (disease problem)", "kind": "share",
        "arms": {
            "gain": INTRO + DISEASE + "If Program A is adopted, 200 people will be saved.\nIf Program B is adopted, there is a 1/3 "
                    "probability that 600 people will be saved and a 2/3 probability that no people will be saved.",
            "loss": INTRO + DISEASE + "If Program A is adopted, 400 people will die.\nIf Program B is adopted, there is a 1/3 "
                    "probability that nobody will die and a 2/3 probability that 600 people will die.",
        },
        "question": {"text": "Which program would you choose?", "options": ["Program A", "Program B"]},
        "measure": {"label": "% choosing the certain program (A)", "option": {"gain": "Program A", "loss": "Program A"}},
        "contrast": ["gain", "loss"],
        "published": {"source": "Many Labs 1 (N = 6,271)", "values": {"gain": 62.2, "loss": 33.5}, "d": 0.60, "d_ci95": [0.55, 0.65],
                      "original": {"source": "Tversky & Kahneman 1981", "values": {"gain": 72.0, "loss": 22.0}, "d": 1.13}},
    },
    {
        "id": "framing_paraphrase", "label": "Gain vs. loss framing (paraphrase: chemical leak)", "kind": "share",
        "arms": {
            "gain": INTRO + SPILL + "Plan 1: 300 residents will be saved.\nPlan 2: a 1/3 chance that all 900 residents will be "
                    "saved and a 2/3 chance that none will be saved.",
            "loss": INTRO + SPILL + "Plan 1: 600 residents will die.\nPlan 2: a 1/3 chance that no residents will die and a 2/3 "
                    "chance that all 900 will die.",
        },
        "question": {"text": "Which plan would you choose?", "options": ["Plan 1", "Plan 2"]},
        "measure": {"label": "% choosing the certain plan (1)", "option": {"gain": "Plan 1", "loss": "Plan 1"}},
        "contrast": ["gain", "loss"],
        "published": None,
    },
    {
        "id": "allow_forbid", "label": "Allowed vs. forbidden wording", "kind": "share",
        "arms": {
            "allow": "A survey you're taking asks you this question:\n\nDo you think the United States should allow public "
                     "speeches against democracy?",
            "forbid": "A survey you're taking asks you this question:\n\nDo you think the United States should forbid public "
                      "speeches against democracy?",
        },
        "question": {"text": "Your answer to the survey question:", "options": ["Yes", "No"]},
        "measure": {"label": "% giving the anti-speech answer (No to allow / Yes to forbid)", "option": {"allow": "No", "forbid": "Yes"}},
        "contrast": ["allow", "forbid"],
        "published": {"source": "Many Labs 1 (N = 6,292)", "values": {"allow": 23.7, "forbid": 7.2}, "d": None,
                      "note": "ML1's published d = 1.96 compares raw 'yes' rates; on the anti-speech answer the difference is ≈ 0.47 (our arithmetic from ML1's percentages).",
                      "original": {"source": "Rugg 1941", "values": {"allow": 62.0, "forbid": 46.0}, "d": 0.65}},
    },
    {
        "id": "anchoring_everest", "label": "Anchoring: height of Mount Everest", "kind": "mean",
        "arms": {
            "low": "A survey you're taking first tells you: \"Mount Everest is taller than 2,000 feet.\"",
            "high": "A survey you're taking first tells you: \"Mount Everest is shorter than 45,500 feet.\"",
        },
        "question": {"text": "How tall do you think Mount Everest is, in feet? Give your best estimate as a whole number.",
                     "scale": [0, 100000], "labels": ["0 feet", "100,000 feet"]},
        "measure": {"label": "mean estimate (feet), answers outside the anchors dropped", "window": [2000, 45500]},
        "contrast": ["high", "low"],
        "published": {"source": "Many Labs 1 (N = 5,627)", "values": {"high": 34501, "low": 11849}, "d": 2.23, "d_ci95": [2.16, 2.30],
                      "note": "ML1's d is on rank-transformed estimates."},
    },
    {
        "id": "anchoring_nyc", "label": "Anchoring: San Francisco to New York City", "kind": "mean",
        "arms": {
            "low": "A survey you're taking first tells you: \"The distance from San Francisco to New York City is longer than 1,500 miles.\"",
            "high": "A survey you're taking first tells you: \"The distance from San Francisco to New York City is shorter than 6,000 miles.\"",
        },
        "question": {"text": "How far do you think it is from San Francisco to New York City, in miles? Give your best estimate as a whole number.",
                     "scale": [0, 20000], "labels": ["0 miles", "20,000 miles"]},
        "measure": {"label": "mean estimate (miles), answers outside the anchors dropped", "window": [1500, 6000]},
        "contrast": ["high", "low"],
        "published": {"source": "Many Labs 1 (N = 5,362)", "values": {"high": 3994, "low": 2851}, "d": 1.17, "d_ci95": [1.11, 1.23],
                      "note": "ML1's d is on rank-transformed estimates."},
    },
    {
        "id": "sunk_cost", "label": "Sunk cost (football ticket)", "kind": "mean",
        "arms": {
            "paid": INTRO + FOOTBALL.format(how="have paid handsomely for"),
            "free": INTRO + FOOTBALL.format(how="have received for free from a friend"),
        },
        "question": {"text": "What do you do, from 1 (definitely stay at home) to 9 (definitely go to the game)?",
                     "scale": [1, 9], "labels": ["definitely stay at home", "definitely go to the game"]},
        "measure": {"label": "mean on 1–9 (9 = definitely go)"},
        "contrast": ["paid", "free"],
        "published": {"source": "Many Labs 1 (N = 6,330)", "values": {"paid": 7.85, "free": 7.24}, "d": 0.27, "d_ci95": [0.22, 0.32],
                      "original": {"source": "Oppenheimer et al. 2009", "values": {"paid": 7.46, "free": 6.93}, "d": 0.23}},
    },
    {
        "id": "sunk_cost_paraphrase", "label": "Sunk cost (paraphrase: concert in the rain)", "kind": "mean",
        "arms": {
            "paid": INTRO + CONCERT.format(how="paid $150 for it"),
            "free": INTRO + CONCERT.format(how="won it for free in a radio giveaway"),
        },
        "question": {"text": "What do you do, from 1 (definitely stay home) to 9 (definitely go to the show)?",
                     "scale": [1, 9], "labels": ["definitely stay home", "definitely go to the show"]},
        "measure": {"label": "mean on 1–9 (9 = definitely go)"},
        "contrast": ["paid", "free"],
        "published": None,
    },
]


def panel_body(exp: dict, pop_id: str, n: int, seed: int) -> dict:
    q = exp["question"]
    question = {"id": "answer", "text": q["text"], "expert": "behavioral_economist", "primary": True}
    if "options" in q:
        question |= {"kind": "single_choice", "options": q["options"]}
    else:
        question |= {"kind": "scale", "scale_min": q["scale"][0], "scale_max": q["scale"][1], "scale_labels": q["labels"]}
    arms = [{"id": "control", "label": "No message", "kind": "control", "control_mode": "none"}]
    arms += [{"id": k, "label": k.replace("_", " ").title(), "kind": "treatment", "format": "other", "text": text}
             for k, text in exp["arms"].items()]
    return {"population_id": pop_id, "title": f"Classic experiment · {exp['label']} · {n} agents · seed {seed}",
            "arms": arms, "questionnaire": "custom", "questions": [question], "sample_size": n, "seed": seed}


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _sd(xs):
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else None


def cohens_d(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    sa, sb = _sd(a), _sd(b)
    pooled = math.sqrt(((len(a) - 1) * sa ** 2 + (len(b) - 1) * sb ** 2) / (len(a) + len(b) - 2))
    return (_mean(a) - _mean(b)) / pooled if pooled > 0 else None


def d_from_props(p1: float, n1: int, p2: float, n2: int) -> float | None:
    """ML1's conversion for 2x2 tables: phi from chi-square, d = 2*phi / sqrt(1 - phi^2)."""
    a, b = p1 * n1, (1 - p1) * n1
    c, d = p2 * n2, (1 - p2) * n2
    den = math.sqrt((a + b) * (c + d) * (a + c) * (b + d))
    if den == 0:
        return None
    phi = (a * d - b * c) / den
    return 2 * phi / math.sqrt(1 - phi ** 2) if abs(phi) < 1 else None


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def analyze(exp: dict, responses: list[dict], seed: int) -> dict:
    """Effect of contrast[0] vs contrast[1] on the measure, with a paired bootstrap over agents."""
    import random

    a_id, b_id = exp["contrast"]
    by_agent: dict[str, dict[str, object]] = {}
    for r in responses:
        if r.get("status") == "ok" and r["arm_id"] in (a_id, b_id):
            by_agent.setdefault(r["agent_id"], {})[r["arm_id"]] = r["answers"].get("answer")

    def score(arm: str, value):
        if value is None:
            return None
        if exp["kind"] == "share":
            return 1.0 if value == exp["measure"]["option"][arm] else 0.0
        lo_hi = exp["measure"].get("window")
        v = float(value)
        if lo_hi and not lo_hi[0] <= v <= lo_hi[1]:
            return None
        return v

    rows = {aid: {arm: score(arm, v) for arm, v in arms.items()} for aid, arms in by_agent.items()}
    a = [x[a_id] for x in rows.values() if x.get(a_id) is not None]
    b = [x[b_id] for x in rows.values() if x.get(b_id) is not None]

    def stats(a: list[float], b: list[float]) -> dict:
        if exp["kind"] == "share":
            pa, pb = _mean(a), _mean(b)
            d = d_from_props(pa, len(a), pb, len(b)) if a and b else None
            return {"a": None if pa is None else 100 * pa, "b": None if pb is None else 100 * pb, "diff": None if pa is None or pb is None else 100 * (pa - pb), "d": d}
        out = {"a": _mean(a), "b": _mean(b), "diff": None if not a or not b else _mean(a) - _mean(b), "d": cohens_d(a, b)}
        if exp["id"].startswith("anchoring") and a and b:
            rk = ranks(a + b)
            out["d_rank"] = cohens_d(rk[: len(a)], rk[len(a):])
        return out

    point = stats(a, b)
    rng = random.Random(f"{exp['id']}:{seed}")
    ids = list(rows)
    boots = []
    for _ in range(1000):
        sample = [rows[rng.choice(ids)] for _ in ids]
        sa = [x[a_id] for x in sample if x.get(a_id) is not None]
        sb = [x[b_id] for x in sample if x.get(b_id) is not None]
        st = stats(sa, sb)
        if st["diff"] is not None:
            boots.append(st["diff"])
    boots.sort()
    ci = [boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]] if boots else [None, None]
    pub = exp.get("published")
    direction_ok = None
    size_ratio = None
    if pub and point["diff"] is not None:
        pdiff = pub["values"][a_id] - pub["values"][b_id]
        direction_ok = (point["diff"] > 0) == (pdiff > 0) and ci[0] is not None and (ci[0] > 0 if pdiff > 0 else ci[1] < 0)
        size_ratio = point["diff"] / pdiff if pdiff else None
    return {
        "n_a": len(a), "n_b": len(b), "n_agents": len(rows),
        "value_a": round(point["a"], 2) if point["a"] is not None else None,
        "value_b": round(point["b"], 2) if point["b"] is not None else None,
        "diff": round(point["diff"], 2) if point["diff"] is not None else None,
        "diff_ci95": [round(x, 2) if x is not None else None for x in ci],
        "d": round(point["d"], 2) if point.get("d") is not None else None,
        "d_rank": round(point["d_rank"], 2) if point.get("d_rank") is not None else None,
        "direction_matches": direction_ok,
        "diff_vs_published": round(size_ratio, 2) if size_ratio is not None else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Replicate classic survey experiments as message tests.")
    ap.add_argument("--agents", type=int, default=150)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--only", nargs="*", help="experiment ids")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(ROOT / "data" / "validation" / "db.json"))
    ap.add_argument("--population", default=None, help="population id (default: the validation population)")
    ap.add_argument("--out", default=str(FIXTURE))
    args = ap.parse_args()
    os.environ["DATA_FILE"] = args.db
    os.environ.setdefault("SIM_STEP_SECONDS", "900")

    from backend.app.config import get_settings
    from backend.app.sim import costs, panel, runner
    from backend.app.sim.models import PanelIn
    from backend.app.storage import get_store

    s = get_settings()
    store = get_store()
    pops = [p for p in store.find("populations", sort="created_at") if p["name"].startswith("OpinionQA validation") and p["status"] == "ready"]
    pop = store.get("populations", args.population) if args.population else (pops[-1] if pops else None)
    if not pop:
        sys.exit("No ready validation population; run scripts/validate.py first (or pass --population).")
    exps = [e for e in EXPERIMENTS if not args.only or e["id"] in args.only]
    persona_tok = costs.persona_tokens(pop.get("transcript_words") or 900, pop.get("reflections_per_expert") or 6)
    total = 0.0
    print(f"Population: {pop['name']} ({pop['ready_count']} ready). Model {s.sim_model} via {s.llm_backend}.")
    for e in exps:
        stim = int(sum(len(t) for t in e["arms"].values()) / len(e["arms"]) / 4) + 60
        est = costs.estimate_panel(args.agents, len(e["arms"]) + 1, 1, 1, persona_tok, stim)
        total += est["usd"]
        print(f"  {e['id']:24s} {est['calls']:>5} calls  ${est['usd']:.2f}  ~{est['minutes']} min")
    print(f"  total ${total:.2f} API-equivalent" + (" (no charge: billed to the Claude Code subscription)" if s.llm_backend == "claude-cli" else ""))
    if args.dry_run:
        return

    out = {"date": date.today().isoformat(),
           "command": f"LLM_BACKEND={s.llm_backend} .venv/bin/python scripts/experiments.py " + " ".join(shlex.quote(a) for a in sys.argv[1:]),
           "model": s.sim_model, "backend": s.llm_backend, "population": {"id": pop["id"], "name": pop["name"], "persona_mode": pop["persona_mode"]},
           "n_agents": args.agents, "experiments": []}
    for e in exps:
        body = panel_body(e, pop["id"], args.agents, args.seed)
        run = next((r for r in store.find("sim_runs", kind="panel", title=body["title"])), None)
        if not run:
            run = panel.create_panel(PanelIn(**body))
        run = drive(runner, store, run["id"])
        res = analyze(e, store.find("sim_results", run_id=run["id"]), args.seed)
        out["experiments"].append({
            "id": e["id"], "label": e["label"], "kind": e["kind"], "measure": e["measure"]["label"], "contrast": e["contrast"],
            "published": e.get("published"), "result": res, "run": {**run_record(run), "results": None},
        })
        print(f"{e['id']}: {res}", flush=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
