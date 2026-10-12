"""Validate simulated respondents against real survey answers (OpinionQA / Pew ATP).

    .venv/bin/python scripts/fetch_opinionqa.py                    # once: download the raw waves (gitignored)
    .venv/bin/python scripts/validate.py --dry-run                 # cost estimate, no model calls
    LLM_BACKEND=claude-cli .venv/bin/python scripts/validate.py --split dev --agents 100
    LLM_BACKEND=claude-cli .venv/bin/python scripts/validate.py --split test

Steps: pick eligible questions (seeded split: a dev set for plumbing checks, a test set for reported
numbers), build one synthetic population matched to the benchmark's demographic margins, ask every
condition's agents the same question blocks through survey runs (the normal step protocol), rake
weights to the benchmark margins, and score OpinionQA's representativeness overall and per group
against the real answers. Agents only ever see question wording and options.

Conditions: interview agents, card-only agents, a demographics-only prompt (all three on the same
sampled people), plus baselines that make no calls: uniform random, the real overall distribution for
every group, and the finite-sample ceiling (real respondents subsampled to our group sizes).

State lives in a separate JSON store (data/validation/db.json), so reruns resume finished work.
Results (derived scores only, never answer distributions) go to --out; test-split results feed
docs/validation.md and the Validation page.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.runs import drive, run_record  # noqa: E402

CONDITIONS = ("interview", "card", "demographics")
DEFAULT_WAVES = (27, 34, 41, 42, 49, 50, 54)
PREAMBLE = ("These questions come from a national survey panel fielded between 2017 and 2019. "
            "Answer as you would have at the time.")
DOC = ROOT / "docs" / "validation.md"
FIXTURE = ROOT / "backend" / "app" / "sim" / "fixtures" / "validation.json"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Validate simulated respondents against OpinionQA.")
    ap.add_argument("--split", choices=("dev", "test"), default="test")
    ap.add_argument("--n-dev", type=int, default=20)
    ap.add_argument("--n-test", type=int, default=100)
    ap.add_argument("--block-size", type=int, default=10)
    ap.add_argument("--population-size", type=int, default=400, help="agents generated for the validation population")
    ap.add_argument("--agents", type=int, default=None, help="agents asked (sampled from the population; default all)")
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--limit", type=int, default=None,
                    help="smoke test: at most this many agents and one block of questions")
    ap.add_argument("--waves", type=int, nargs="+", default=list(DEFAULT_WAVES))
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--dry-run", action="store_true", help="print the cost estimate and exit")
    ap.add_argument("--max-usd", type=float, default=5.0, help="refuse any single run estimated above this")
    ap.add_argument("--db", default=str(ROOT / "data" / "validation" / "db.json"))
    ap.add_argument("--raw", default=str(ROOT / "data" / "opinionqa" / "raw"))
    ap.add_argument("--out", default=None, help="results JSON (default: the fixture for --split test, data/validation/ otherwise)")
    ap.add_argument("--render-docs", action="store_true", help="only re-render docs/validation.md from the fixture")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    if args.render_docs:
        render_docs(json.loads(FIXTURE.read_text()))
        return
    os.environ["DATA_FILE"] = args.db
    os.environ["MONGODB_URI"] = ""  # always the local JSON store above, even if .env points at a real database
    os.environ.setdefault("SIM_STEP_SECONDS", "900")
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    from backend.app.config import get_settings
    from backend.app.sim import costs, jobs, runner, survey
    from backend.app.sim import validation as V
    from backend.app.sim.models import PopulationIn, SurveyIn
    from backend.app.storage import get_store

    s = get_settings()
    store = get_store()
    raw = Path(args.raw)
    if not (raw / f"W{args.waves[0]}" / "responses.csv").exists():
        sys.exit(f"No OpinionQA data in {raw}. Run scripts/fetch_opinionqa.py first.")

    # ---- questions
    waves = {w: V.load_wave(raw, w) for w in args.waves}
    pool = [q for wd in waves.values() for q in wd["questions"] if V.eligible(q, wd["respondents"])[0]]
    dev, test = V.split_questions(pool, args.n_dev, args.n_test, seed=args.seed)
    questions = dev if args.split == "dev" else test
    blocks = V.make_blocks(questions, args.block_size, seed=args.seed)
    if args.limit:
        blocks = blocks[:1]
        questions = [q for q in questions if q["key"] in {x["id"] for x in blocks[0]["questions"]}]
    real = {}
    for w, wd in waves.items():
        real.update(V.real_distributions(wd, {q["key"] for q in questions if q["wave"] == w}))
    margins = V.pew_margins(list(waves.values()))
    print(f"{len(pool)} eligible questions; {args.split} split: {len(questions)} questions in {len(blocks)} blocks "
          f"of {args.block_size}", flush=True)

    # ---- population (same people for every condition)
    pop_name = f"OpinionQA validation (n={args.population_size}, seed {args.seed})"
    pop = next((p for p in store.find("populations", name=pop_name)), None)
    n_ask = min(args.limit or args.agents or args.population_size, args.agents or args.population_size)
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    estimates = {}
    if not pop or pop.get("status") != "ready":
        estimates["population (interview personas)"] = costs.estimate_populate(args.population_size, "interview")
    persona_tok = {"interview": costs.persona_tokens(900, 6), "card": 400, "demographics": 120}
    for c in conditions:
        estimates[f"survey: {c}"] = costs.estimate_survey(n_ask, len(blocks), args.block_size, persona_tok[c])
    print_estimates(estimates, s)
    too_big = [k for k, e in estimates.items() if e["usd"] > args.max_usd]
    if too_big:
        sys.exit(f"Estimated above ${args.max_usd} per run: {', '.join(too_big)}. Lower the size or raise --max-usd.")
    if args.dry_run:
        return

    if not pop:
        body = PopulationIn(
            name=pop_name, size=args.population_size, preset="us_adults", targets=V.population_targets(margins),
            oversample={"race": {"black": 1.5, "hispanic": 1.3, "asian": 1.5, "other": 1.5}},
            persona_mode="interview", card_detail="light", seed=args.seed,
            description="Matched to the OpinionQA / Pew ATP margins for the validation harness.",
        )
        pop = jobs.create_synthetic(body)
    pop_run = store.get("sim_runs", pop["populate_run_id"]) if pop.get("populate_run_id") else None
    if pop_run:
        pop_run = drive(runner, store, pop_run["id"])
    pop = store.get("populations", pop["id"])
    if pop["status"] != "ready":
        sys.exit(f"Population isn't ready ({pop['status']}); rerun to resume.")

    agents_all = {a["id"]: a for a in store.find("agents", population_id=pop["id"], persona_status="ready")}
    runs = {}
    for c in conditions:
        title = f"OpinionQA {args.split} · {c} · {len(questions)}q · {n_ask} agents · seed {args.seed}"
        run = next((r for r in store.find("sim_runs", kind="survey", title=title)), None)
        if not run:
            run = survey.create_survey(SurveyIn(
                population_id=pop["id"], title=title, blocks=blocks, persona_style=c, preamble=PREAMBLE,
                sample_size=n_ask if n_ask < len(agents_all) else None, seed=args.seed,
            ))
        runs[c] = drive(runner, store, run["id"])

    # ---- scoring
    asked_ids = runs[conditions[0]]["config"]["agent_ids"]
    asked = [agents_all[i] for i in asked_ids]
    weights_list, diag = V.rake_weights(asked, margins, [a.get("base_weight") or 1.0 for a in asked])
    weights = {a["id"]: w for a, w in zip(asked, weights_list)}
    group_sizes = {}
    for a in asked:
        for attr, lvl in V.agent_groups(a["demographics"]).items():
            group_sizes[f"{attr}={lvl}"] = group_sizes.get(f"{attr}={lvl}", 0) + 1

    scores = {}
    for c, run in runs.items():
        answers = survey.answers_by_agent(run)
        sim = V.sim_distributions(answers, {i: agents_all[i] for i in asked_ids}, weights, questions)
        scores[c] = V.representativeness(V.sim_predictor(sim), questions, real, seed=args.seed)
        scores[c]["dispersion"] = V.dispersion(questions, sim)
        scores[c]["by_wave"] = {str(w): V.representativeness(V.sim_predictor(sim), [q for q in questions if q["wave"] == w],
                                                             real, seed=args.seed)["overall"]
                                for w in sorted({q["wave"] for q in questions})}
    scores["uniform"] = V.representativeness(V.uniform_predictor, questions, real, seed=args.seed)
    scores["overall_distribution"] = V.representativeness(V.overall_predictor(real), questions, real, seed=args.seed)
    ceiling = V.sampling_ceiling(waves, questions, real, group_sizes, len(asked), seed=args.seed)
    human = V.human_group_baseline(questions, real)
    real_dispersion = V.dispersion(questions, real)

    out = {
        "benchmark": "OpinionQA (Santurkar et al. 2023), Pew American Trends Panel",
        "date": date.today().isoformat(),
        "command": "LLM_BACKEND=" + s.llm_backend + " .venv/bin/python scripts/validate.py " + " ".join(shlex.quote(a) for a in sys.argv[1:]),
        "model": s.sim_model,
        "backend": s.llm_backend,
        "agent_effort": s.sim_agent_effort,
        "split": args.split,
        "seed": args.seed,
        "waves": args.waves,
        "n_eligible_questions": len(pool),
        "n_questions": len(questions),
        "block_size": args.block_size,
        "n_agents": len(asked),
        "population": {"id": pop["id"], "size": pop["agent_count"], "persona_mode": pop["persona_mode"],
                       "card_detail": pop.get("card_detail"), "preset": pop.get("preset")},
        "weighting": {"deff": diag["deff"], "n_eff": diag["n_eff"], "max_error": diag.get("max_error")},
        "group_sizes": group_sizes,
        "questions": [{"key": q["key"], "wave": q["wave"], "n_options": len(q["options"])} for q in questions],
        "scores": scores,
        "ceiling": ceiling,
        "human_groups_vs_overall": human,
        "real_dispersion": real_dispersion,
        "runs": {c: run_record(r) for c, r in runs.items()},
        "population_run": run_record(pop_run) if pop_run else None,
    }
    dest = Path(args.out) if args.out else (FIXTURE if args.split == "test" and not args.limit else
                                            ROOT / "data" / "validation" / f"{args.split}_results.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {dest}")
    print_summary(out)
    if dest == FIXTURE:
        render_docs(out)


def print_estimates(estimates: dict, s) -> None:
    print(f"\nEstimate (model {s.sim_model}, backend {s.llm_backend}; API-equivalent cost, i.e. Anthropic API list price for the same tokens):")
    total = 0.0
    for k, e in estimates.items():
        total += e["usd"]
        print(f"  {k:36s} {e['calls']:>6,} calls  {e['input_tokens']:>12,} in  {e['output_tokens']:>10,} out  "
              f"${e['usd']:.2f}  ~{e['minutes']} min")
    print(f"  {'total':36s} ${total:.2f}" + ("  (no charge: the shim bills the Claude Code subscription)" if s.llm_backend == "claude-cli" else ""))
    print(flush=True)


def print_summary(out: dict) -> None:
    sc = out["scores"]
    print(f"\n{'condition':24s} {'overall R':>10s} {'group mean':>11s} {'worst group':>12s}")
    for name in [*CONDITIONS, "uniform", "overall_distribution"]:
        if name in sc:
            x = sc[name]
            print(f"{name:24s} {x['overall']['R']!s:>10s} {x['group_mean']!s:>11s} {x['group_worst']!s:>12s}")
    c = out["ceiling"]
    print(f"{'sampling ceiling':24s} {c['overall']['R']!s:>10s} {c['group_mean']!s:>11s} {c['group_worst']!s:>12s}")


LABELS = {
    "interview": "Interview agents",
    "card": "Card-only agents",
    "demographics": "Demographics-only prompt",
    "uniform": "Uniform random",
    "overall_distribution": "Real overall distribution for every group",
}


def render_docs(out: dict) -> None:
    """Replace the generated section of docs/validation.md with tables from the results JSON."""
    sc = out["scores"]
    lines = [
        f"Run {out['date']}: `{out['command']}`  ",
        f"Model `{out['model']}` via `{out['backend']}`, agent effort `{out['agent_effort']}`; {out['n_questions']} test "
        f"questions ({out['n_eligible_questions']} eligible) from ATP waves {', '.join('W' + str(w) for w in out['waves'])}, "
        f"blocks of {out['block_size']}; {out['n_agents']} agents (population {out['population']['size']}, "
        f"{out['population']['persona_mode']} personas, card detail `{out['population']['card_detail']}`), raked to the "
        f"benchmark margins (design effect {out['weighting']['deff']}).",
        "",
        "| Condition | Overall R [95% CI] | Mean group R | Worst group R |",
        "|---|---|---|---|",
    ]
    for name in [*CONDITIONS, "uniform", "overall_distribution"]:
        if name not in sc:
            continue
        x = sc[name]
        o = x["overall"]
        ci = f" [{o['lo']}, {o['hi']}]" if o.get("lo") is not None else ""
        lines.append(f"| {LABELS[name]} | {o['R']}{ci} | {x['group_mean']} | {x['group_worst']} |")
    c = out["ceiling"]
    lines.append(f"| Sampling ceiling (real respondents, same group sizes) | {c['overall']['R']} | {c['group_mean']} | {c['group_worst']} |")
    if out.get("real_dispersion"):
        rd = out["real_dispersion"]
        lines += ["", "How spread out the answers are (overall distributions, mean over questions; entropy 0 = everyone gives one answer, "
                  "1 = evenly spread; modal share = share giving the most common answer):", "",
                  "| | Entropy | Modal share |", "|---|---|---|", f"| Real respondents | {rd['entropy']} | {rd['modal_share']} |"]
        for name in CONDITIONS:
            if name in sc and sc[name].get("dispersion"):
                lines.append(f"| {LABELS[name]} | {sc[name]['dispersion']['entropy']} | {sc[name]['dispersion']['modal_share']} |")
        waves = sorted({w for c in CONDITIONS if c in sc for w in (sc[c].get("by_wave") or {})}, key=int)
        if waves:
            lines += ["", "Overall R by survey wave:", "", "| Wave | Questions | " + " | ".join(LABELS[c] for c in CONDITIONS if c in sc) + " |",
                      "|---|---|" + "---|" * len([c for c in CONDITIONS if c in sc])]
            for w in waves:
                nq = next(sc[c]["by_wave"][w]["n_questions"] for c in CONDITIONS if c in sc)
                lines.append(f"| W{w} | {nq} | " + " | ".join(str(sc[c]["by_wave"][w]["R"]) for c in CONDITIONS if c in sc) + " |")
    h = out["human_groups_vs_overall"]
    lines += ["", f"Real groups vs the overall population on these questions (OpinionQA's human reference): mean {h['mean']}, worst {h['worst']}.", ""]
    groups = list(next(iter(sc.values()))["groups"].keys())
    conds = [c for c in CONDITIONS if c in sc]
    lines += ["| Group | n agents | " + " | ".join(LABELS[c] for c in conds) + " | Overall distribution | Ceiling |",
              "|---|---|" + "---|" * (len(conds) + 2)]
    for g in groups:
        cells = [str(sc[c]["groups"][g]["R"]) for c in conds]
        lines.append(f"| {g} | {out['group_sizes'].get(g, 0)} | " + " | ".join(cells) +
                     f" | {sc['overall_distribution']['groups'][g]['R']} | {c_get(out['ceiling'], g)} |")
    lines += ["", "| Run | Calls | Wall time | Input (uncached / cache write / cache read) | Output | API-equivalent cost |", "|---|---|---|---|---|---|"]
    recs = dict(out["runs"])
    if out.get("population_run"):
        recs = {"population": out["population_run"], **recs}
    for k, r in recs.items():
        lines.append(f"| {k} | {r['calls']:,} | {r.get('wall_minutes', '—')} min | {r['input_tokens']:,} / {r['cache_creation_input_tokens']:,} / "
                     f"{r['cache_read_input_tokens']:,} | {r['output_tokens']:,} | ${r['usd_list_price']:.2f} |")
    exp_file = FIXTURE.parent / "experiments.json"
    if exp_file.exists():
        lines += experiment_lines(json.loads(exp_file.read_text()))
    text = DOC.read_text()
    start, end = "<!-- results:start -->", "<!-- results:end -->"
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    DOC.write_text(head + start + "\n" + "\n".join(lines) + "\n" + end + tail)
    print(f"rendered {DOC}")


def experiment_lines(ex: dict) -> list[str]:
    def val(kind: str, v):
        if v is None:
            return "—"
        return f"{v:.1f}%" if kind == "share" else f"{v:,.0f}" if abs(v) >= 100 else f"{v:.2f}"

    out = ["", "### Classic survey experiments", "",
           f"Run {ex['date']}: `{ex['command']}`; model `{ex['model']}` via `{ex['backend']}`; {ex['n_agents']} agents from "
           f"{ex['population']['name']} ({ex['population']['persona_mode']} personas), every agent in every condition.", "",
           "| Experiment | Measure | Simulated | Difference [95% CI] | Published (Many Labs 1) | Direction | Size vs published | API-equivalent cost |",
           "|---|---|---|---|---|---|---|---|"]
    for e in ex["experiments"]:
        a, b = e["contrast"]
        r, p = e["result"], e.get("published")
        unit = " pts" if e["kind"] == "share" else ""
        diff = f"{val('mean', r['diff'])}{unit} [{val('mean', r['diff_ci95'][0])}, {val('mean', r['diff_ci95'][1])}]"
        pub = f"{a} {val(e['kind'], p['values'][a])} / {b} {val(e['kind'], p['values'][b])}" if p else "—"
        direction = "—" if r["direction_matches"] is None else ("matches" if r["direction_matches"] else "doesn't match")
        if r["direction_matches"] and r.get("diff_vs_published") is not None and not 0.25 <= r["diff_vs_published"] <= 4:
            direction = "direction only (size far off)"
        size = f"{r['diff_vs_published']}×" if r.get("diff_vs_published") is not None else "—"
        out.append(f"| {e['label']} | {e['measure']} | {a} {val(e['kind'], r['value_a'])} / {b} {val(e['kind'], r['value_b'])} | "
                   f"{diff} | {pub} | {direction} | {size} | ${e['run']['usd_list_price']:.2f} |")
    return out


def c_get(ceiling: dict, g: str):
    return (ceiling.get("groups") or {}).get(g, {}).get("R")


if __name__ == "__main__":
    main()
