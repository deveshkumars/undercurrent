from backend.app.sim.candidate import fit_slope, parse_segment

from .conftest import drive


def test_segment_parser():
    assert parse_segment("Independents")({"party": "independent"}) is True
    assert parse_segment("Women")({"gender": "male"}) is False
    under35 = parse_segment("Under 35")
    assert under35({"age": 34}) is True and under35({"age": 35}) is False and under35({}) is None
    combo = parse_segment("Hispanic women 18-29")
    assert combo({"race": "hispanic", "gender": "female", "age": 22}) is True
    assert combo({"race": "hispanic", "gender": "male", "age": 22}) is False
    assert parse_segment("College grads")({"education": "postgrad"}) is True
    assert parse_segment("Non-college white men")({"education": "some_college", "race": "white", "gender": "male"}) is True
    assert parse_segment("Union households") is None


def test_fit_slope_through_origin():
    rows = [{"sim": s, "sim_se": 0.1, "measured": 0.5 * s, "measured_se": 0.2, "signal": "clear"} for s in (-4, -2, 2, 6)]
    fit = fit_slope(rows)
    assert abs(fit["beta"] - 0.5) < 1e-6 and fit["r"] > 0.99 and fit["sign_agreement"] == 1.0


def _setup(client, size=60):
    cand = client.post("/api/candidates/demo").json()
    pop = client.post("/api/sim/populations", json={"name": "Lakeshore voters", "size": size, "seed": 5,
                                                    "candidate_id": cand["id"]}).json()
    assert pop["geography"] == "Lakeshore State (fictional)"
    drive(client, pop["populate_run_id"])
    return cand, pop


def test_calibration_and_apply(sim_client):
    cand, pop = _setup(sim_client)
    hub = sim_client.get(f"/api/candidates/{cand['id']}/sim").json()
    assert set(hub["poll_segments"]) == {"Independents", "Women", "Under 35"}
    seg = sim_client.get(f"/api/candidates/{cand['id']}/sim/segments", params={"population_id": pop["id"]}).json()
    assert {s["segment"] for s in seg["segments"]} == {"Independents", "Women", "Under 35"} and not seg["unmapped"]
    assert abs(seg["suggested_targets"]["Women"] - 0.52) < 0.05
    ctx = sim_client.get(f"/api/candidates/{cand['id']}/sim/context").json()["context"]
    assert "Morgan Ellery" in ctx and "poll" not in ctx.lower()  # no poll numbers leak into agent context

    run = sim_client.post(f"/api/candidates/{cand['id']}/sim/calibration", json={"population_id": pop["id"]}).json()
    assert run["kind"] == "calibration"
    run = drive(sim_client, run["id"])
    assert run["status"] == "done", run
    res = run["results"]
    rows = {r["segment"]: r for r in res["segments"]}
    assert rows["All"]["poll"]["cand"] > 30 and rows["All"]["sim"]["n"] > 0
    assert res["mae"] is not None
    applied = sim_client.post(f"/api/sim/runs/{run['id']}/apply-calibration").json()["results"]
    assert applied["applied"] and applied["mae_after"] < res["mae"]
    after = {r["segment"]: r for r in applied["after"]}
    assert abs(after["All"]["diff"]) < 1.0
    pop2 = sim_client.get(f"/api/sim/populations/{pop['id']}").json()
    assert pop2["calibration"]["applied"]

    # a panel can now use the calibrated weights
    panel = sim_client.post("/api/sim/runs/panel", json={
        "population_id": pop["id"], "candidate_id": cand["id"], "title": "Cal panel", "weight_set": "calibrated",
        "arms": [{"id": "control", "label": "Placebo", "kind": "control"},
                 {"id": "t", "label": "Ad", "kind": "treatment", "text": "BOOST message"}]}).json()
    assert panel["config"]["subject"] == "Morgan Ellery"
    done = drive(sim_client, panel["id"])
    assert done["results"]["weight_set"] == "calibrated"
    assert any(c["dim"].startswith("poll: ") for c in done["results"]["segments"])


def test_backtest(sim_client):
    from backend.app.sample_data import DEMO_EVENTS

    cand, pop = _setup(sim_client, 30)
    # the fake moves the thermometer (and so vote choice) by 4x the planted topline effect
    sim_client.fake.event_effects = {e["title"]: 4 * e["effects"]["All"] for e in DEMO_EVENTS}
    hub = sim_client.get(f"/api/candidates/{cand['id']}/sim").json()
    events = [e["id"] for e in hub["eligible_events"]][:6]
    assert len(events) >= 4
    run = sim_client.post(f"/api/candidates/{cand['id']}/sim/backtest",
                          json={"population_id": pop["id"], "event_ids": events, "sample_size": 30}).json()
    run = drive(sim_client, run["id"])
    assert run["status"] == "done", run
    res = run["results"]
    assert len(res["events"]) == len(events) and res["beta"] is not None
    assert res["r"] > 0.3
    pop2 = sim_client.get(f"/api/sim/populations/{pop['id']}").json()
    assert pop2["backtest"]["beta"] == res["beta"] and pop2["backtest"]["predictor"] == "thermometer"
    assert res["beta"] > 0  # thermometer moves track the planted poll effects

    # later panels for this candidate get effects translated into expected poll movement
    panel = drive(sim_client, sim_client.post("/api/sim/runs/panel", json={
        "population_id": pop["id"], "candidate_id": cand["id"], "title": "Adjusted",
        "arms": [{"id": "control", "label": "Placebo", "kind": "control"},
                 {"id": "t", "label": "Ad", "kind": "treatment", "text": "BOOST message"}]}).json()["id"])
    adj = panel["results"]["backtest_adjusted"]
    raw = panel["results"]["effects"]["t"]["thermometer"]["est"]
    assert adj["predictor"] == "thermometer" and abs(adj["effects"]["t"]["est"] - res["beta"] * raw) < 0.05
