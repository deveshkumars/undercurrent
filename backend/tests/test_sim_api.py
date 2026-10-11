import threading

from .conftest import drive


def _population(client, size=40, mode="interview", **extra):
    body = {"name": "Test pop", "size": size, "persona_mode": mode, "seed": 3, **extra}
    r = client.post("/api/sim/populations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _ready_population(client, size=40):
    pop = _population(client, size)
    run = drive(client, pop["populate_run_id"])
    assert run["status"] == "done", run
    pop = client.get(f"/api/sim/populations/{pop['id']}").json()
    assert pop["status"] == "ready" and pop["ready_count"] == size
    return pop


PANEL = {
    "title": "Boost test",
    "subject": "Sam Rivera",
    "opponent": "Lee Park",
    "questionnaire": "political",
    "arms": [
        {"id": "control", "label": "Placebo", "kind": "control", "control_mode": "placebo"},
        {"id": "boost", "label": "Boost ad", "kind": "treatment", "format": "ad_script", "text": "BOOST: Sam Rivera will cut costs."},
        {"id": "flat", "label": "Flat ad", "kind": "treatment", "format": "ad_script", "text": "A plain message about roads."},
    ],
}


def test_meta_and_preview(sim_client):
    meta = sim_client.get("/api/sim/meta").json()
    assert meta["enabled"] and "us_registered_voters" in meta["presets"]
    assert any(t["id"] == "empathy_priming_100" for t in meta["intervention_templates"])
    prev = sim_client.post("/api/sim/populations/preview", json={"name": "x", "size": 200, "targets": {"party": {"democrat": 50, "republican": 20, "independent": 30}}}).json()
    party = prev["weighting"]["margins"]["party"]
    assert abs(party["democrat"]["weighted"] - 0.5) < 0.01
    assert prev["estimate"]["calls"] == 200


def test_demographic_population_is_ready_without_llm(sim_client):
    pop = _population(sim_client, 25, mode="demographic")
    assert pop["status"] == "ready" and pop["populate_run_id"] is None
    agents = sim_client.get(f"/api/sim/populations/{pop['id']}/agents", params={"limit": 5}).json()
    assert agents["total"] == 25 and len(agents["agents"]) == 5
    assert "transcript" not in agents["agents"][0]
    assert sim_client.fake.calls == []


def test_populate_then_panel_recovers_planted_effect(sim_client):
    pop = _ready_population(sim_client, 60)
    agent = sim_client.get(f"/api/sim/agents/{sim_client.get(f'/api/sim/populations/{pop['id']}/agents').json()['agents'][0]['id']}").json()
    assert "PARTY=" in agent["transcript"] and agent["reflections"]["psychologist"]

    r = sim_client.post("/api/sim/runs/panel", json={**PANEL, "population_id": pop["id"]})
    assert r.status_code == 201, r.text
    run = drive(sim_client, r.json()["id"])
    assert run["status"] == "done", run
    res = run["results"]
    assert res["n_agents"] == 60 and res["n_errors"] == 0
    therm = res["effects"]["boost"]["thermometer"]
    assert therm["est"] > 1 and therm["lo"] > 0  # Democrats moved +10, so the whole sample moved
    flat = res["effects"]["flat"]["thermometer"]
    assert flat["lo"] <= 0 <= flat["hi"]
    dem = next(c for c in res["segments"] if c["treatment"] == "boost" and c["dim"] == "party" and c["level"] == "democrat")
    rep = next(c for c in res["segments"] if c["treatment"] == "boost" and c["dim"] == "party" and c["level"] == "republican")
    assert abs(dem["est"] - 10) < 0.01 and abs(rep["est"]) < 0.01
    assert res["summary"]["headline"]
    assert res["quotes"] and res["toplines"]["control"]["vote_choice"]["shares"]
    # one call per agent per arm, plus the summary; the persona block was sent as a cached block
    panel_calls = [c for c in sim_client.fake.calls if c["output"].startswith("PanelAnswers")]
    assert len(panel_calls) == 60 * 3
    assert all(c["cache_system"] for c in panel_calls)

    csv = sim_client.get(f"/api/sim/runs/{run['id']}/export.csv")
    assert csv.status_code == 200 and csv.text.count("\n") == 60 * 3 + 1
    again = sim_client.post(f"/api/sim/runs/{run['id']}/recompute").json()
    assert again["results"]["effects"]["boost"]["thermometer"]["est"] == therm["est"]


def test_concurrent_steps_conflict(sim_client, monkeypatch):
    pop = _population(sim_client, 20)
    rid = pop["populate_run_id"]
    from backend.app.sim import personas

    gate = threading.Event()
    real = personas.generate_persona

    def slow(agent, population):
        gate.wait(5)
        return real(agent, population)

    monkeypatch.setattr("backend.app.sim.jobs.generate_persona", slow)
    out = {}

    def first():
        out["a"] = sim_client.post(f"/api/sim/runs/{rid}/step")

    t = threading.Thread(target=first)
    t.start()
    import time

    for _ in range(50):
        if sim_client.get(f"/api/sim/runs/{rid}").json()["lease_owner"]:
            break
        time.sleep(0.02)
    second = sim_client.post(f"/api/sim/runs/{rid}/step")
    gate.set()
    t.join()
    assert second.status_code == 409
    assert out["a"].status_code == 200
    run = drive(sim_client, rid)
    assert run["status"] == "done"
    agents = sim_client.get(f"/api/sim/populations/{pop['id']}/agents", params={"limit": 100}).json()
    assert agents["total"] == 20  # no duplicates


def test_cancel_and_budget(sim_client):
    pop = _ready_population(sim_client, 20)
    run = sim_client.post("/api/sim/runs/panel", json={**PANEL, "population_id": pop["id"]}).json()
    assert sim_client.post(f"/api/sim/runs/{run['id']}/cancel").json()["status"] == "canceled"
    assert sim_client.post(f"/api/sim/runs/{run['id']}/step").status_code == 409

    run = sim_client.post("/api/sim/runs/panel", json={**PANEL, "population_id": pop["id"]}).json()
    sim_client.patch(f"/api/sim/runs/{run['id']}", json={"max_calls": 10})
    run = drive(sim_client, run["id"])
    assert run["status"] == "budget_exhausted" and run["progress"]["calls"] <= 10
    sim_client.patch(f"/api/sim/runs/{run['id']}", json={"max_calls": 1000})
    assert sim_client.post(f"/api/sim/runs/{run['id']}/resume").json()["status"] == "running"
    assert drive(sim_client, run["id"])["status"] == "done"


def test_custom_questions_are_routed(sim_client):
    pop = _ready_population(sim_client, 12)
    body = {**PANEL, "population_id": pop["id"], "questionnaire": "custom", "arms": PANEL["arms"][:2], "questions": [
        {"id": "trust", "text": "How much do you trust Sam?", "kind": "scale", "scale_min": 0, "scale_max": 10},
        {"id": "pick", "text": "Pick one", "kind": "single_choice", "options": ["a", "b", "c"]},
    ]}
    run = drive(sim_client, sim_client.post("/api/sim/runs/panel", json=body).json()["id"])
    assert run["status"] == "done"
    assert run["config"]["routes"] == {"trust": "psychologist", "pick": "psychologist"}
    assert "trust" in run["results"]["effects"]["boost"]


def test_csv_import(sim_client):
    start = sim_client.post("/api/sim/populations/import", json={"name": "Survey", "consent_attested": False})
    assert start.status_code == 422
    pop = sim_client.post("/api/sim/populations/import", json={"name": "Survey", "consent_attested": True}).json()
    csv = (
        "respondent_id,Name,Email,age,gender,race,educ,party_id,ideology,weight,Q_most_important_issue,Q_trust_gov\n"
        "r1,Ann Smith,a@x.com,34,Female,White,Bachelor's degree,Democrat,Liberal,1.2,Housing,Rarely\n"
        "r2,Bo Li,b@x.com,67,Male,Asian,High school graduate,Republican,Conservative,0.8,Taxes,Never\n"
        'r3,Cy Diaz,c@x.com,22,Female,Hispanic,"Some college, no degree",Independent,Moderate,1.0,Jobs,Sometimes\n'
    )
    chunk = sim_client.post(f"/api/sim/populations/{pop['id']}/import/chunk", json={"csv": csv}).json()
    assert chunk["imported"] == 3
    assert set(chunk["columns"]["pii_dropped"]) == {"Name", "Email"}
    assert chunk["columns"]["mapping"]["weight"] == "weight"
    done = sim_client.post(f"/api/sim/populations/{pop['id']}/import/finish", json={"rake": False}).json()
    assert done["status"] == "generating"
    run = drive(sim_client, done["populate_run_id"])
    assert run["status"] == "done"
    agents = sim_client.get(f"/api/sim/populations/{pop['id']}/agents").json()["agents"]
    a = sim_client.get(f"/api/sim/agents/{agents[0]['id']}").json()
    assert a["demographics"]["party"] == "democrat" and a["demographics"]["education"] == "bachelors"
    assert a["demographics"]["age"] == 34 and a["demographics"]["age_band"] == "30-44"
    assert "Ann" not in str(a["raw"]) and "a@x.com" not in str(a["raw"])
    assert a["raw"]["Q most important issue"] == "Housing"
    assert a["reflections"] and a["source"] == "csv_survey"
    assert abs(a["weight"] - 1.2) < 1e-6


def test_vercel_json_store_disables_sims(sim_client, monkeypatch):
    from backend.app import config

    monkeypatch.setenv("VERCEL", "1")
    config.get_settings.cache_clear()
    r = sim_client.get("/api/sim/meta")
    assert r.status_code == 503 and "MONGODB_URI" in r.json()["detail"]
    assert sim_client.get("/api/meta").json()["sim"]["enabled"] is False


def test_delete_population_cascades(sim_client):
    pop = _ready_population(sim_client, 10)
    run = drive(sim_client, sim_client.post("/api/sim/runs/panel", json={**PANEL, "population_id": pop["id"]}).json()["id"])
    assert sim_client.delete(f"/api/sim/populations/{pop['id']}").json()["deleted"]
    assert sim_client.get(f"/api/sim/runs/{run['id']}").status_code == 404
    assert sim_client.get(f"/api/sim/runs/{run['id']}/responses").status_code == 404
