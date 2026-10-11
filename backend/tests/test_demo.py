"""The built-in demo scenarios load from fixtures and display with no model calls."""

import pytest

from backend.app.sim import demo


pytestmark = pytest.mark.skipif(not demo.FIXTURE.exists(), reason="no demo fixture (run scripts/seed_demos.py)")


@pytest.fixture()
def demo_client(sim_client, monkeypatch):
    monkeypatch.setenv("SIM_DEMO_FIXTURES", "on")
    return sim_client


def test_demos_load_once_and_display_without_model_calls(demo_client):
    listing = demo_client.get("/api/sim/demos").json()
    kinds = sorted(r["kind"] for r in listing["runs"])
    assert kinds.count("panel") == 1 and kinds.count("social") == 4  # base run + apology, transparency, control
    assert all(r["status"] == "done" and r["demo"] for r in listing["runs"])
    assert listing["generated"]["command"].startswith("LLM_BACKEND=")

    product = next(r for r in listing["runs"] if r["kind"] == "panel")
    assert len(product["highlight"]["arms"]) == 3
    run = demo_client.get(f"/api/sim/runs/{product['id']}").json()
    assert run["results"]["toplines"] and run["results"]["n_agents"] == 150
    assert demo_client.get(f"/api/sim/runs/{product['id']}/responses").status_code == 200

    branches = [r for r in listing["runs"] if r["kind"] == "social" and r["parent_run_id"]]
    assert len(branches) == 3 and all(r["highlight"]["ner"] is not None for r in branches)
    base = next(r for r in listing["runs"] if r["kind"] == "social" and not r["parent_run_id"])
    assert len(demo_client.get(f"/api/sim/runs/{base['id']}/ticks").json()) == 72
    assert demo_client.get(f"/api/sim/runs/{base['id']}/posts").json()["total"] > 0
    assert demo_client.get(f"/api/sim/runs/{base['id']}/network").json()["roles"]
    cmp = demo_client.get(f"/api/sim/runs/{branches[0]['id']}/compare", params={"with": branches[1]["id"]}).json()
    assert len(cmp["runs"]) == 2

    pops = demo_client.get("/api/sim/populations").json()
    assert any(p.get("demo") and p["status"] == "ready" for p in pops)
    assert demo_client.fake.calls == []  # nothing here touches the model

    # a second load of the same fixture version is a no-op
    from backend.app.sim import demo as D

    D._loaded_for.clear()
    assert D.ensure_loaded() is False
