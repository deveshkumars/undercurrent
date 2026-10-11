"""Validation harness: metric arithmetic, question eligibility, and an offline survey run whose planted
party effect the scoring must recover. No real survey data is needed (or read) here."""

import csv

import pytest

from backend.app.sim import prompts as SP
from backend.app.sim import validation as V

from .conftest import drive


# ---------------------------------------------------------------- metric


def test_wasserstein_matches_hand_computation():
    pos = [1.0, 2.0, 3.0, 4.0]
    assert V.wasserstein([1, 0, 0, 0], [0, 0, 0, 1], pos) == pytest.approx(3.0)
    assert V.wd_norm([1, 0, 0, 0], [0, 0, 0, 1], pos) == pytest.approx(1.0)  # extremes: max distance
    # moving half the mass one step: 0.5
    assert V.wasserstein([0.5, 0.5, 0, 0], [0, 1, 0, 0], pos) == pytest.approx(0.5)
    assert V.wd_norm([0.25] * 4, [0.25] * 4, pos) == 0.0


def test_hedge_option_sits_between_the_poles():
    # OpinionQA puts "Neither" at the mean of the other positions (1, 2, 1.5)
    pos = [1.0, 2.0, 1.5]
    assert V.wasserstein([0, 0, 1], [1, 0, 0], pos) == pytest.approx(0.5)
    assert V.wd_norm([0, 0, 1], [0, 1, 0], pos) == pytest.approx(0.5)


def test_distribution_drops_refusals_and_bad_indices():
    d = V.distribution([(0, 1.0), (1, 3.0), ("refused", 5.0), (None, 2.0), (7, 1.0)], 2)
    assert d == pytest.approx([0.25, 0.75])
    assert V.distribution([("refused", 1.0)], 3) is None


def _wave(tmp_path, rows, questions):
    folder = tmp_path / "W99"
    folder.mkdir()
    with open(folder / "info.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["", "key", "question", "references", "option_ordinal"])
        for i, (key, opts, ordinal) in enumerate(questions):
            w.writerow([i, key, f"Question {key}?", repr(opts + ["Refused"]), repr(ordinal)])
    keys = [q[0] for q in questions]
    with open(folder / "responses.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["QKEY", "FORM_W99", "POLPARTY", "AGE", "WEIGHT_W99", *keys])
        for r in rows:
            w.writerow([r["id"], r["form"], r["party"], "30-49", r["w"], *[r.get(k, "") for k in keys]])
    return tmp_path


def test_eligibility_keeps_form_splits_and_drops_skip_logic(tmp_path):
    opts = ["Yes", "No"]
    rows = []
    for i in range(200):
        form = "Form 1" if i % 2 else "Form 2"
        r = {"id": i, "form": form, "party": "Democrat", "w": 1.0, "ALL": "Yes", "SKIP": "No" if i % 3 else ""}
        if form == "Form 1":
            r["SPLIT"] = "Yes"
        rows.append(r)
    raw = _wave(tmp_path, rows, [("ALL", opts, [1, 2]), ("SPLIT", opts, [1, 2]), ("SKIP", opts, [1, 2]),
                                 ("CAT", ["a", "b", "c"], [1, 1, 1])])
    wd = V.load_wave(raw, 99)
    verdict = {q["key"]: V.eligible(q, wd["respondents"]) for q in wd["questions"]}
    assert verdict["ALL"][0] and verdict["SPLIT"][0]
    assert verdict["SKIP"] == (False, "skip logic")
    assert verdict["CAT"] == (False, "not ordinal")


def test_real_distributions_use_weights_and_groups(tmp_path):
    rows = [
        {"id": 1, "form": "F", "party": "Democrat", "w": 3.0, "Q": "Yes"},
        {"id": 2, "form": "F", "party": "Republican", "w": 1.0, "Q": "No"},
        {"id": 3, "form": "F", "party": "Other", "w": 1.0, "Q": "Refused"},
    ]
    raw = _wave(tmp_path, rows, [("Q", ["Yes", "No"], [1, 2])])
    wd = V.load_wave(raw, 99)
    real = V.real_distributions(wd, {"Q"})
    assert real["Q"]["overall"] == pytest.approx([0.75, 0.25])
    assert real["Q"]["groups"]["party"]["democrat"]["dist"] == [1.0, 0.0]
    assert "independent" not in real["Q"]["groups"]["party"]  # "Other" maps to independent but only refused


def test_split_and_blocks_are_seeded_and_uniform():
    qs = [{"key": f"Q{w}_{i}", "wave": w, "text": "t", "options": ["a", "b"], "positions": [1, 2]}
          for w in (1, 2) for i in range(15)]
    dev, test = V.split_questions(qs, 4, 20, seed=1)
    assert len(dev) == 4 and len(test) == 20 and not {q["key"] for q in dev} & {q["key"] for q in test}
    assert V.split_questions(qs, 4, 20, seed=1) == (dev, test)
    blocks = V.make_blocks(test, 5)
    assert len(blocks) == 4 and all(len(b["questions"]) == 5 for b in blocks)
    with pytest.raises(ValueError):
        V.make_blocks(test[:7], 5)


def test_agent_group_mapping():
    g = V.agent_groups({"age": 34, "race": "asian", "income": "60-100k", "education": "postgrad", "party": "independent"})
    assert g == {"age": "30-49", "race": "other", "income": "30-100k", "education": "postgrad", "party": "independent"}


# ---------------------------------------------------------------- offline survey run


def _questions(n):
    return [{"key": f"Q{i}", "wave": 99, "text": f"Do you like thing {i}?", "options": ["Yes", "Maybe", "No"],
             "positions": [1.0, 2.0, 3.0]} for i in range(n)]


def test_survey_run_recovers_planted_party_effect(sim_client):
    pop = sim_client.post("/api/sim/populations", json={"name": "Val", "size": 60, "persona_mode": "demographic", "seed": 4}).json()
    qs = _questions(6)
    blocks = V.make_blocks(qs, 3)
    preamble = "These questions come from a survey fielded in 2019."
    body = {"population_id": pop["id"], "title": "Validation (card)", "blocks": blocks, "persona_style": "card",
            "preamble": preamble, "seed": 1}
    r = sim_client.post("/api/sim/runs/survey", json=body)
    assert r.status_code == 201, r.text
    run = drive(sim_client, r.json()["id"])
    assert run["status"] == "done", run
    assert run["results"]["n_complete"] == 60 and run["results"]["invalid_answer_rate"] == 0

    calls = [c for c in sim_client.fake.calls if c["output"] == "SurveyBlock"]
    assert len(calls) == 60 * 2
    # prompts are a pure function of question wording: nothing about real answers can leak in
    allowed = {SP.survey_task(b["questions"], preamble) for b in blocks}
    assert all(c["task"] in allowed for c in calls)
    assert all(c["system"] == SP.AGENT_SYSTEM and c["cache_system"] for c in calls)

    from backend.app.sim import survey
    from backend.app.storage import get_store

    full = get_store().get("sim_runs", run["id"])
    answers = survey.answers_by_agent(full)
    agents = {a["id"]: a for a in get_store().find("agents", population_id=pop["id"])}
    sim = V.sim_distributions(answers, agents, {aid: a["weight"] for aid, a in agents.items()}, qs)
    # planted: democrats answer Yes, republicans No, independents Maybe
    assert sim["Q0"]["groups"]["party"]["democrat"]["dist"] == [1.0, 0.0, 0.0]
    assert sim["Q0"]["groups"]["party"]["republican"]["dist"] == [0.0, 0.0, 1.0]

    # a benchmark that matches the planted effect scores R = 1 for party groups; uniform scores lower
    real = {q["key"]: {"overall": sim[q["key"]]["overall"], "groups": {"party": {
        "democrat": {"dist": [1.0, 0.0, 0.0]}, "republican": {"dist": [0.0, 0.0, 1.0]}, "independent": {"dist": [0.0, 1.0, 0.0]}}}}
        for q in qs}
    rep = V.representativeness(V.sim_predictor(sim), qs, real)
    uni = V.representativeness(V.uniform_predictor, qs, real)
    assert rep["groups"]["party=democrat"]["R"] == 1.0 and rep["overall"]["R"] == 1.0
    assert uni["groups"]["party=democrat"]["R"] == pytest.approx(0.5)
    flat = V.representativeness(V.overall_predictor(real), qs, real)
    assert flat["groups"]["party=democrat"]["R"] < 1.0


def test_persona_styles_differ_in_what_they_reveal():
    agent = {"first_name": "Ana", "demographics": {"age": 40, "gender": "female", "party": "democrat", "vote_2024": "dem"},
             "traits": {"occupation": "nurse", "big5": {}, "news_diet": ["local TV"], "salient_issues": ["costs"]},
             "transcript": "Interviewer: hi\nRespondent: hello", "reflections": {"psychologist": ["calm"]}}
    from backend.app.sim.survey import persona_for

    demo = persona_for(agent, "demographics")
    card = persona_for(agent, "card")
    interview = persona_for(agent, "interview")
    assert "nurse" not in demo and "2024" not in demo and "Party identification: democrat" in demo
    assert "nurse" in card and "<interview>" not in card and "calm" not in card
    assert "<interview>" in interview and "calm" in interview


def test_classic_experiment_analysis_scores_like_for_like():
    from scripts import experiments as X

    exp = next(e for e in X.EXPERIMENTS if e["id"] == "allow_forbid")
    responses = []
    for i in range(40):
        # anti-speech answer: "No" to allow for 30/40, "Yes" to forbid for 10/40
        responses.append({"status": "ok", "agent_id": f"a{i}", "arm_id": "allow", "answers": {"answer": "No" if i < 30 else "Yes"}})
        responses.append({"status": "ok", "agent_id": f"a{i}", "arm_id": "forbid", "answers": {"answer": "Yes" if i < 10 else "No"}})
    res = X.analyze(exp, responses, seed=1)
    assert res["value_a"] == 75.0 and res["value_b"] == 25.0 and res["diff"] == 50.0
    assert res["direction_matches"] is True  # published: 23.7% vs 7.2%, same sign, CI excludes 0

    anchor = next(e for e in X.EXPERIMENTS if e["id"] == "anchoring_everest")
    rs = [{"status": "ok", "agent_id": f"a{i}", "arm_id": arm, "answers": {"answer": v}}
          for i in range(10) for arm, v in (("high", 30000 + i), ("low", 10000 + i))]
    rs.append({"status": "ok", "agent_id": "x", "arm_id": "high", "answers": {"answer": 90000}})  # outside the anchors: dropped
    res = X.analyze(anchor, rs, seed=1)
    assert res["n_a"] == 10 and res["value_a"] == 30004.5 and res["d_rank"] > 2
    assert X.d_from_props(0.622, 3100, 0.335, 3100) == pytest.approx(0.60, abs=0.01)  # ML1's framing d


def test_spread_is_normalized_entropy():
    assert V.spread([1.0, 0.0, 0.0]) == 0.0
    assert V.spread([0.25] * 4) == pytest.approx(1.0)
    d = V.dispersion([{"key": "q"}], {"q": {"overall": [0.5, 0.5]}})
    assert d == {"entropy": 1.0, "modal_share": 0.5}
