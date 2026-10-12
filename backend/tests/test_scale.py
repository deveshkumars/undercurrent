"""The step protocol at 1,000 agents: overlapping steppers and an expired lease never duplicate or
lose results, and every call that was made is counted."""

import threading
import time

import pytest

from backend.app.sim import runner
from backend.app.storage import get_store

N = 1000
PANEL = {
    "title": "Scale test",
    "subject": "Brightloop",
    "questionnaire": "product",
    "arms": [
        {"id": "control", "label": "Control", "kind": "control", "control_mode": "placebo"},
        {"id": "a", "label": "A", "kind": "treatment", "format": "ad_script", "text": "BOOST: version A of the ad."},
        {"id": "b", "label": "B", "kind": "treatment", "format": "ad_script", "text": "Version B of the ad, plainer."},
    ],
}


@pytest.fixture()
def big(sim_client, monkeypatch):
    from backend.app import config

    monkeypatch.setenv("SIM_MAX_AGENTS", str(N))
    monkeypatch.setenv("SIM_MAX_CALLS_PER_RUN", "10000")
    monkeypatch.setenv("SIM_STEP_SECONDS", "0.05")  # many short steps, so steppers really interleave
    config.get_settings.cache_clear()
    pop = sim_client.post("/api/sim/populations", json={"name": "Big", "size": N, "persona_mode": "demographic", "seed": 9}).json()
    assert pop["status"] == "ready" and pop["agent_count"] == N, pop
    return sim_client, pop


def _panel_calls(fake) -> int:
    return sum(1 for c in fake.calls if c["output"].startswith("PanelAnswers"))


def _check_complete(run_id: str, n: int, arms: int) -> None:
    results = get_store().find("sim_results", run_id=run_id)
    ids = [r["id"] for r in results]
    assert len(ids) == len(set(ids)) == n * arms
    per_agent: dict[str, int] = {}
    for r in results:
        per_agent[r["agent_id"]] = per_agent.get(r["agent_id"], 0) + 1
    assert len(per_agent) == n and set(per_agent.values()) == {arms}


def test_config_limit_is_enforced_and_raisable(sim_client, monkeypatch):
    from backend.app import config

    r = sim_client.post("/api/sim/populations", json={"name": "Too big", "size": 1000, "persona_mode": "demographic"})
    assert r.status_code == 422 and "SIM_MAX_AGENTS" in r.json()["detail"]
    monkeypatch.setenv("SIM_MAX_AGENTS", "1000")
    config.get_settings.cache_clear()
    assert sim_client.post("/api/sim/populations", json={"name": "OK", "size": 1000, "persona_mode": "demographic"}).status_code == 201


def test_overlapping_steppers_on_a_1000_agent_panel(big):
    client, pop = big
    run = client.post("/api/sim/runs/panel", json={**PANEL, "population_id": pop["id"], "seed": 4}).json()
    assert run["total"] == N
    statuses: list[int] = []
    lock = threading.Lock()

    def stepper():
        for _ in range(2000):
            cur = get_store().get("sim_runs", run["id"])
            if cur["status"] in ("done", "failed", "canceled", "paused", "budget_exhausted"):
                return
            code = client.post(f"/api/sim/runs/{run['id']}/step").status_code
            with lock:
                statuses.append(code)

    threads = [threading.Thread(target=stepper) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = get_store().get("sim_runs", run["id"])
    assert final["status"] == "done", final["status"]
    assert 409 in statuses and statuses.count(200) > 10  # the steppers really did collide
    _check_complete(run["id"], N, 3)
    prog = final["progress"]
    assert prog["done"] == N and prog["failed"] == 0
    # every model call made is counted exactly once (3 per agent + the debrief)
    assert prog["calls"] == len(client.fake.calls) == 3 * N + 1
    assert final["results"]["n_agents"] == N and final["results"]["effects"]["a"]


def test_expired_lease_takeover_keeps_results_and_counts_all_spend(big, monkeypatch):
    client, pop = big
    fake = client.fake
    gate, entered = threading.Event(), threading.Event()
    first = threading.Lock()
    claimed = []

    def slow_first_call(*args, **kw):  # the run's first model call (the late step's) hangs, like a stuck request
        with first:
            mine = not claimed
            claimed.append(1)
        if mine:
            entered.set()
            gate.wait(20)
        return fake(*args, **kw)

    from backend.app import llm

    monkeypatch.setattr(llm, "structured", slow_first_call)
    run = client.post("/api/sim/runs/panel", json={**PANEL, "population_id": pop["id"], "seed": 5}).json()

    late_status: list[int] = []
    late = threading.Thread(target=lambda: late_status.append(client.post(f"/api/sim/runs/{run['id']}/step").status_code))
    late.start()
    assert entered.wait(5)
    # the late step still holds the lease; let it expire, then another caller takes over and finishes the run
    get_store().update("sim_runs", run["id"], {"lease_expires_at": time.time() - 1})
    for _ in range(3000):
        cur = get_store().get("sim_runs", run["id"])
        if cur["status"] == "done":
            break
        assert client.post(f"/api/sim/runs/{run['id']}/step").status_code == 200
    assert get_store().get("sim_runs", run["id"])["status"] == "done"
    before = {r["id"]: r for r in get_store().find("sim_results", run_id=run["id"])}

    gate.set()  # the late step wakes up, finishes its batch, finds its lease gone
    late.join(10)
    assert late_status == [200]

    final = get_store().get("sim_runs", run["id"])
    assert final["status"] == "done"
    _check_complete(run["id"], N, 3)
    after = {r["id"]: r for r in get_store().find("sim_results", run_id=run["id"])}
    assert after == before  # the late step's results were discarded, not written over the finished run
    prog = final["progress"]
    assert prog["done"] == N  # the overlapped units aren't double counted...
    assert prog["calls"] == _panel_calls(fake) + 1 > 3 * N  # ...but every call made, including the late step's, is
    assert any("outlived its lease" in line for line in final["log"])


def test_benchmark_summary_math():
    from scripts.benchmark import summarize_calls

    rows = [
        {"schema": "PanelAnswers", "ok": True, "seconds": 2.0, "t": 102.0, "input_tokens": 100, "output_tokens": 50,
         "cache_read_input_tokens": 0, "cache_creation_input_tokens": 900, "cache_creation_1h_input_tokens": 900},
        {"schema": "PanelAnswers", "ok": True, "seconds": 4.0, "t": 104.0, "input_tokens": 100, "output_tokens": 50,
         "cache_read_input_tokens": 900, "cache_creation_input_tokens": 0, "cache_creation_1h_input_tokens": 0},
        {"schema": "PanelAnswers", "ok": False, "seconds": 1.0, "t": 161.0, "error": "x"},
    ]
    s = summarize_calls(rows)
    assert s["calls"] == 3 and s["failed_calls"] == 1
    assert s["total_input_tokens"] == 2000 and s["cache_hit_rate_tokens"] == 0.45
    assert s["calls_with_cache_read"] == 0.5
    assert s["call_span_minutes"] == 1.0  # first call started at t=100, last ended at t=161
    assert s["usd_api_equivalent"] == round((200 * 0.10 + 900 * 2 * 0.10 + 900 * 0.01 + 100 * 0.50) / 1e6, 4)
