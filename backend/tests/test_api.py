import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FILE", str(tmp_path / "db.json"))
    monkeypatch.setenv("LLM_BACKEND", "anthropic")
    # empty (not unset) so a developer's real .env can't leak in through the dotenv loader
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("MONGODB_URI", "")
    monkeypatch.setenv("ACCESS_CODE", "")
    monkeypatch.setenv("PUBLIC_DEMO", "")
    from backend.app import config, llm, storage

    config.get_settings.cache_clear()
    storage.get_store.cache_clear()
    llm.get_client.cache_clear()
    from backend.app.main import app

    yield TestClient(app)
    config.get_settings.cache_clear()
    storage.get_store.cache_clear()
    llm.get_client.cache_clear()


def test_demo_flow(client):
    cand = client.post("/api/candidates/demo").json()
    listed = client.get("/api/candidates").json()
    assert listed[0]["id"] == cand["id"] and listed[0]["poll_count"] > 100

    a = client.get(f"/api/candidates/{cand['id']}/analysis", params={"segment": "Independents"}).json()
    assert a["segment"] == "Independents" and a["stats"]["poll_count"] > 50
    assert len(a["events"]) == 13 and a["themes"]


def test_csv_import_and_crud(client):
    cid = client.post("/api/candidates", json={"name": "Test Candidate"}).json()["id"]
    csv = "End Date,Pollster,N,Candidate,Opponent,Notes\n2026-05-01,A,800,45%,47%,x\n05/08/2026,B,600,46,46,y\nbad,row,,,\n"
    r = client.post(f"/api/candidates/{cid}/polls/import", json={"csv": csv}).json()
    assert r["imported"] == 2 and r["error_count"] == 1 and r["ignored_columns"] == ["Notes"]

    ev_csv = 'date,type,title,topics\n2026-05-04,Town Hall,Hall,"economy; jobs"\n'
    r = client.post(f"/api/candidates/{cid}/events/import", json={"csv": ev_csv}).json()
    assert r["imported"] == 1
    ev = client.get(f"/api/candidates/{cid}/events").json()[0]
    assert ev["type"] == "town_hall" and ev["topics"] == ["economy", "jobs"]

    assert client.delete(f"/api/candidates/{cid}/events/{ev['id']}").json()["deleted"]
    assert client.delete(f"/api/candidates/{cid}").json()["deleted"]
    assert client.get(f"/api/candidates/{cid}").status_code == 404


def test_ai_routes_explain_missing_key(client):
    cid = client.post("/api/candidates/demo").json()["id"]
    r = client.post(f"/api/candidates/{cid}/insights", json={})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_access_code(client, monkeypatch):
    from backend.app import config

    monkeypatch.setenv("ACCESS_CODE", "s3cret")
    config.get_settings.cache_clear()
    assert client.get("/api/candidates").status_code == 401
    assert client.get("/api/candidates", headers={"x-access-code": "s3cret"}).status_code == 200
    assert client.get("/api/meta").json()["access_required"] is True
    assert client.get("/api/health").status_code == 200


def test_validation(client):
    cid = client.post("/api/candidates", json={"name": "X"}).json()["id"]
    assert client.post(f"/api/candidates/{cid}/polls", json={"date": "2026-01-01", "value": 140}).status_code == 422
    assert client.post(f"/api/candidates/{cid}/forecast", json={"title": "t", "content": "short"}).status_code == 422

