from .conftest import drive

SOCIAL = {
    "title": "Acme recall",
    "focal_subject": "Acme Foods",
    "n_agents": 30,
    "duration_hours": 3,
    "tick_minutes": 10,
    "max_calls_per_tick": 6,
    "seed_event": {"at_minute": 0, "kind": "event", "label": "Recall news",
                   "event": {"author": "media_center", "text": "Acme Foods recalls 2 million jars of peanut butter.", "importance": 2}},
    "seed": 11,
}


def _pop(client):
    pop = client.post("/api/sim/populations", json={"name": "Social pop", "size": 40, "seed": 2, "persona_mode": "demographic"}).json()
    assert pop["status"] == "ready"
    return pop


def test_social_run_branch_and_compare(sim_client):
    pop = _pop(sim_client)
    r = sim_client.post("/api/sim/runs/social", json={**SOCIAL, "population_id": pop["id"]})
    assert r.status_code == 201, r.text
    run = drive(sim_client, r.json()["id"])
    assert run["status"] == "done", run
    ticks = sim_client.get(f"/api/sim/runs/{run['id']}/ticks").json()
    assert len(ticks) == 18 and ticks[0]["events"]
    assert sum(t["served"] for t in ticks) > 0
    res = run["results"]
    assert res["activations"] > 0 and res["comments"] + res["posts"] > 0
    assert res["ner"] == 1.0  # every fake reaction is angry
    posts = sim_client.get(f"/api/sim/runs/{run['id']}/posts").json()
    assert posts["total"] > 0
    first = next(p for p in posts["posts"] if p.get("event"))
    thread = sim_client.get(f"/api/sim/runs/{run['id']}/posts", params={"root": first["id"]}).json()["posts"]
    assert thread[0]["id"] == first["id"]
    net = sim_client.get(f"/api/sim/runs/{run['id']}/network").json()
    assert net["roles"]["media"] == 3 and net["roles"]["ordinary"] + net["roles"].get("opinion_leader", 0) == 30

    branches = sim_client.post(f"/api/sim/runs/{run['id']}/branch", json={
        "tick": 6, "title": "Apology", "interventions": [
            {"at_minute": 60, "kind": "event", "label": "Apology",
             "event": {"author": "official", "text": "We are sorry and we are fixing it.", "importance": 1}}]}).json()
    assert len(branches) == 2 and all(b["branch_tick"] == 6 for b in branches)
    for b in branches:
        assert b["cursor"] == 6
        done = drive(sim_client, b["id"])
        assert done["status"] == "done"
    bt = sim_client.get(f"/api/sim/runs/{branches[0]['id']}/ticks").json()
    assert [t["tick"] for t in bt] == list(range(18))
    assert any("Apology" in e for t in bt for e in t["events"])
    cmp = sim_client.get(f"/api/sim/runs/{branches[0]['id']}/compare", params={"with": branches[1]["id"]}).json()
    assert cmp["from_tick"] == 6 and len(cmp["runs"]) == 2
    # posts before the branch point are shared with the parent
    parent_posts = {p["id"] for p in sim_client.get(f"/api/sim/runs/{run['id']}/posts").json()["posts"]}
    branch_posts = {p["id"] for p in sim_client.get(f"/api/sim/runs/{branches[1]['id']}/posts").json()["posts"]}
    assert "p1" in parent_posts and "p1" in branch_posts


def test_priming_and_policy_interventions(sim_client):
    pop = _pop(sim_client)
    body = {**SOCIAL, "population_id": pop["id"], "duration_hours": 1, "interventions": [
        {"at_minute": 0, "kind": "node_control", "label": "Prime",
         "node_control": {"selector": {"fraction": 0.5}, "action": "prime", "text": "You check facts first.", "duration_min": 120}},
        {"at_minute": 10, "kind": "platform_policy", "label": "Less viral", "platform_policy": {"w_p": 0.1}},
    ]}
    run = drive(sim_client, sim_client.post("/api/sim/runs/social", json=body).json()["id"])
    assert run["status"] == "done"
    primed = [c for c in sim_client.fake.calls if c["output"] == "SocialActivation" and "You check facts first." in c["task"]]
    social_calls = [c for c in sim_client.fake.calls if c["output"] == "SocialActivation"]
    assert social_calls and len(primed) < len(social_calls) or len(social_calls) <= 2
    ticks = sim_client.get(f"/api/sim/runs/{run['id']}/ticks").json()
    assert any("ranking changed" in e for t in ticks for e in t["events"])
