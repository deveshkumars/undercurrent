"""Unit tests for the deterministic parts: sampling, raking, statistics, social dynamics, storage, LLM requests."""

import json
import math
import random
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from backend.app.sim import demographics as D
from backend.app.sim import dynamics, feed, hawkes, metrics, network
from backend.app.sim.personas import build_traits, map_columns, parse_rows


# ---------------------------------------------------------------- sampling & weighting


def test_sampling_is_deterministic_and_hits_targets():
    a = D.sample(300, "us_registered_voters", seed=9)
    b = D.sample(300, "us_registered_voters", seed=9)
    assert a[0] == b[0]
    rows, base, margins = D.sample(2000, "us_adults", {"party": {"democrat": 0.5, "republican": 0.2, "independent": 0.3}}, seed=1)
    raw_dem = sum(r["party"] == "democrat" for r in rows) / len(rows)
    assert abs(raw_dem - 0.5) < 0.04  # tilting the conditionals already lands close
    ages = {band: sum(r["age_band"] == band for r in rows) for band in ("18-29", "30-44", "45-64", "65+")}
    assert ages == {"18-29": 400, "30-44": 520, "45-64": 640, "65+": 440}  # exact root counts
    w, diag = D.rake(rows, base, margins)
    assert diag["converged"] and diag["max_error"] < 1e-3
    assert abs(diag["margins"]["party"]["democrat"]["weighted"] - 0.5) < 1e-3
    assert abs(sum(w) / len(w) - 1) < 1e-9


def test_raking_trims_and_skips_missing():
    rows = [{"gender": "female", "party": None}] * 5 + [{"gender": "male", "party": "democrat"}] * 95
    w, diag = D.rake(rows, [1.0] * 100, {"gender": {"female": 0.5, "male": 0.5}, "party": {"democrat": 1.0}})
    assert max(w) / (sum(w) / len(w)) <= 5.0 + 1e-6
    assert diag["trimmed"] > 0


def test_oversample_gives_lower_base_weights():
    rows, base, _ = D.sample(500, "us_registered_voters", oversample={"party": {"independent": 3.0}}, seed=4)
    ind = [b for r, b in zip(rows, base) if r["party"] == "independent"]
    assert ind and all(abs(b - 1 / 3) < 1e-9 for b in ind)


def test_traits_are_stable_and_bounded():
    demo = {"age": 70, "age_band": "65+", "party": "republican", "ideology": "conservative", "education": "hs_or_less"}
    t1, t2 = build_traits(demo, (1, 2)), build_traits(demo, (1, 2))
    assert t1 == t2
    assert all(0 <= v <= 1 for v in t1["big5"].values()) and t1["activity"] > 0
    assert t1["psych_type"] in ("curiosity_seeking", "self_actualization", "bandwagon", "cathartic_venting", "anti_authority")


def test_csv_value_mapping():
    cols = map_columns(["Respondent_ID", "Full Name", "Phone", "Age", "PID3", "Q1"])
    assert cols["mapping"]["party"] == "PID3" and set(cols["pii_dropped"]) == {"Full Name", "Phone"}
    parsed = parse_rows("age,party,lean,income\n45-64,Lean Democrat,Democrat,\"$75,000 to $99,999\"\n", "survey")
    demo = parsed["rows"][0]["demographics"]
    assert demo["age_band"] == "45-64" and demo["party"] == "independent" and demo["lean"] == "dem"
    assert demo["income"] == "60-100k"


# ---------------------------------------------------------------- statistics


def test_linearized_and_bootstrap_agree_on_simple_data():
    rng = random.Random(1)
    ds = [rng.gauss(2.0, 4.0) for _ in range(400)]
    ws = [1.0] * 400
    lin = metrics.linearized(ds, ws)
    assert abs(lin["se"] - 4 / math.sqrt(400)) < 0.05
    boot = metrics.bootstrap({"d": (ds, ws)}, 400, 400, random.Random(2))["d"]
    assert abs((boot[1] - boot[0]) - (lin["hi"] - lin["lo"])) < 0.25


def test_bootstrap_coverage():
    covered = 0
    for rep in range(60):
        rng = random.Random(rep)
        ds = [rng.gauss(1.0, 3.0) for _ in range(80)]
        lo, hi = metrics.bootstrap({"d": (ds, [1.0] * 80)}, 80, 300, random.Random(rep + 1000))["d"]
        covered += lo <= 1.0 <= hi
    assert 0.85 <= covered / 60 <= 1.0


def test_benjamini_hochberg():
    flags = metrics.benjamini_hochberg([0.001, 0.008, 0.039, 0.041, 0.6, None], q=0.05)
    assert flags == [True, True, False, False, False, False]


def test_paired_effects_choice_in_points():
    q = {"id": "v", "kind": "single_choice", "options": ["yes", "no"]}
    recs = [{"id": str(i), "w": 1.0, "num": {}, "cat": {"c": {"v": {"no": 1.0}}, "t": {"v": {"yes" if i < 30 else "no": 1.0}}},
             "open": {}, "reasoning": {}} for i in range(100)]
    eff = metrics.paired_effects(recs, [q], ["t"], "c", B=200)
    assert abs(eff["t"]["v"]["options"]["yes"]["est"] - 30.0) < 1e-6
    trans = metrics.transitions(recs, q, "t", "c")
    assert abs(trans["no"]["yes"] - 0.3) < 1e-9


def test_social_metrics():
    assert metrics.emotional_concentration({e: 1 for e in dynamics.EMOTIONS}) == pytest.approx(0.0)
    assert metrics.emotional_concentration({"angry": 5, "happy": 0}) == pytest.approx(1.0)
    assert metrics.stance_polarization([1, 1, -1, -1]) == 1.0 and metrics.stance_polarization([1, 1, 0]) == 0.0
    assert metrics.cascade_histogram([1, 1, 2, 5, 40]) == {"1": 2, "2": 1, "3-4": 0, "5-8": 1, "9-16": 0, "17+": 1}


# ---------------------------------------------------------------- social dynamics


def test_hawkes_baseline_rate_and_branching():
    p = hawkes.params({})
    lam = hawkes.intensity(0, 14 * 60, p, 100, [], [])  # circadian factor is 1 at 14:00
    assert lam == pytest.approx(p["mu"])
    assert hawkes.expected_activations(lam, 100, 60) == pytest.approx(1.0)
    jump = hawkes.endo_jump(p, 100)
    assert jump * 100 / (60 * p["beta_int"]) == pytest.approx(p["branching"])
    lam_ev = hawkes.intensity(140, 14 * 60, p, 100, [[0, 0.08]], [])
    assert lam_ev - p["mu"] * hawkes.circadian(14 * 60 + 140, p["circadian_amp"]) == pytest.approx(0.08 * math.exp(-0.005 * 140))
    assert hawkes.circadian(20 * 60, 0.3) == pytest.approx(1.3)


def test_network_homophily():
    agents = []
    for i in range(120):
        party = ["democrat", "republican", "independent"][i % 3]
        agents.append({"id": f"a{i}", "first_name": "x", "demographics": {"party": party, "ideology": "moderate", "age_band": "30-44"},
                       "traits": {"activity": 1.0, "big5": {"E": 0.5}, "social_media_use": "daily"}})
    acc = network.build(agents, [("official", "Gov")], seed=1)
    summ = network.summary(acc)
    assert summ["same_party_follow_share"] > 0.45  # base rate would be ~1/3
    assert summ["roles"]["opinion_leader"] == 6 and summ["roles"]["media"] == 3


def _state():
    accounts = {"me": {"id": "me", "role": "ordinary", "slant": 0.0, "follows": ["f"], "name": "me"},
                "f": {"id": "f", "role": "ordinary", "slant": 0.0, "follows": [], "name": "f"},
                "o": {"id": "o", "role": "ordinary", "slant": 0.9, "follows": [], "name": "o"}}
    posts = [{"id": f"p{i}", "author": "f" if i < 3 else "o", "minute": i, "type": "short_post", "root": f"p{i}", "parent": None,
              "text": "t", "topics": [], "stance": 0.0, "likes": 0, "reposts": 0, "comments": 0} for i in range(12)]
    return {"accounts": accounts, "agents": {"me": {"seen": [], "stance": 0.0, "topics": []}}, "posts": posts}


def test_feed_slots_and_no_reexposure():
    st = _state()
    p = feed.params({"k": 5, "r_explore": 0.2})
    first, _ = feed.build(st, "me", 20, p, random.Random(1))
    assert len(first) == 5
    assert {x["id"] for x in first} >= {"p2", "p1"}  # relationship channel gets priority
    second, _ = feed.build(st, "me", 21, p, random.Random(2))
    assert not ({x["id"] for x in first} & {x["id"] for x in second})


def test_emotion_decay_and_contagion():
    e = dynamics.decay({"angry": 0.9}, {"angry": 0.1}, 180, 180)
    assert e["angry"] == pytest.approx(0.5)
    c = dynamics.contagion({x: 0.0 for x in dynamics.EMOTIONS}, [({"emotion": "fear", "intensity": 1.0}, 1.0)], 0.15)
    assert c["fear"] == pytest.approx(0.15) and c["angry"] == 0
    mem = []
    for i in range(40):
        mem = dynamics.remember(mem, {"minute": i, "importance": 0.4, "topics": [], "text": f"saw post {i}"})
    assert len(mem) == 30
    hits = dynamics.recall(mem + [{"minute": 39, "importance": 1, "topics": ["recall"], "text": "peanut butter recall"}],
                           "peanut butter", {"recall"}, 40, k=1)
    assert "peanut" in hits[0]["text"]


# ---------------------------------------------------------------- storage


def test_store_compare_and_set_and_files(tmp_path):
    from backend.app.storage import JsonFileStore

    store = JsonFileStore(tmp_path / "db.json")
    store.insert("candidates", {"id": "c1", "name": "x"})
    store.insert("sim_runs", {"id": "r1", "version": 0})
    assert store.update_if("sim_runs", "r1", {"version": 0}, {"version": 1})["version"] == 1
    assert store.update_if("sim_runs", "r1", {"version": 0}, {"version": 2}) is None
    store.upsert_many("sim_results", [{"id": "a", "run_id": "r1", "v": 1}, {"id": "b", "run_id": "r1", "v": 2}])
    store.upsert_many("sim_results", [{"id": "a", "run_id": "r1", "v": 3}])
    assert store.count("sim_results", run_id="r1") == 2
    assert store.find("sim_results", fields=["v"], sort="id") == [{"id": "a", "v": 3}, {"id": "b", "v": 2}]
    assert (tmp_path / "db.sim_results.json").exists()
    core = json.loads((tmp_path / "db.json").read_text())
    assert set(core) == {"candidates", "polls", "events", "reports"}
    reopened = JsonFileStore(tmp_path / "db.json")
    assert reopened.get("sim_runs", "r1")["version"] == 1 and reopened.get("candidates", "c1")


# ---------------------------------------------------------------- LLM request shape


class Out(BaseModel):
    answer: str


class _Stream:
    def __init__(self, kwargs, sink):
        sink.append(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=Out(answer="ok"), usage=usage, model="claude-haiku-5-5")


class _Client:
    def __init__(self):
        self.sent = []
        self.options = []
        self.messages = SimpleNamespace(stream=lambda **kw: _Stream(kw, self.sent))

    def with_options(self, **kw):
        self.options.append(kw)
        return self


@pytest.fixture()
def fake_client(monkeypatch):
    from backend.app import config, llm

    monkeypatch.setenv("LLM_BACKEND", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-5-5")
    config.get_settings.cache_clear()
    client = _Client()
    monkeypatch.setattr(llm, "get_client", lambda: client)
    yield client
    config.get_settings.cache_clear()


def test_structured_request_shapes(fake_client):
    from backend.app import llm
    from backend.app.prompts import SYSTEM_PROMPT

    llm.structured("task", Out, "dossier")
    old = fake_client.sent[-1]
    assert old["system"] == SYSTEM_PROMPT and "thinking" not in old
    assert old["messages"][0]["content"][0] == {"type": "text", "text": "dossier", "cache_control": {"type": "ephemeral"}}
    assert "temperature" not in old

    llm.structured("tail", Out, system="SYS", cache_system=True, blocks=[llm.Block("persona", cache=True)], thinking="off",
                   effort="low", timeout=30, max_retries=1)
    new = fake_client.sent[-1]
    assert new["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert [b["text"] for b in new["messages"][0]["content"]] == ["persona", "tail"]
    assert "cache_control" not in new["messages"][0]["content"][1]
    assert new["thinking"] == {"type": "disabled"} and new["output_config"] == {"effort": "low"}
    assert fake_client.options[-1] == {"timeout": 30, "max_retries": 1}
    with pytest.raises(ValueError):
        llm.structured("t", Out, "d", cache_system=True, blocks=[llm.Block("a", True), llm.Block("b", True), llm.Block("c", True)])


def test_thinking_param_by_model():
    from backend.app.llm import thinking_param

    assert thinking_param("claude-haiku-5-5", "off") == {"type": "disabled"}
    assert thinking_param("claude-sonnet-5-5", "off") == {"type": "between_tools"}
    assert thinking_param("claude-opus-5-5", "off") is None
    assert thinking_param("claude-opus-5-5", "adaptive") == {"type": "adaptive"}


def test_usd_prices_one_hour_cache_writes_at_double():
    from backend.app.sim import costs

    base = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 1_000_000}
    five_min = costs.usd(base, "claude-haiku-5-5")
    one_hour = costs.usd(base | {"cache_creation_1h_input_tokens": 1_000_000}, "claude-haiku-5-5")
    assert round(five_min, 4) == 0.125 and round(one_hour, 4) == 0.2
    half = costs.usd(base | {"cache_creation_1h_input_tokens": 500_000}, "claude-haiku-5-5")
    assert round(half, 4) == 0.1625
