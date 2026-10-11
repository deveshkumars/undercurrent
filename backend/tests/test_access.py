"""Public demo mode: visitors without the access code can read the saved demos and validation results,
and nothing else. Every route in the app is checked, so a new endpoint can't slip through."""

import re

import pytest
from fastapi.testclient import TestClient

from backend.app.access import OPEN_PATHS, VISITOR_GET

CODE = "s3cret"


def _client(monkeypatch, tmp_path, fake_llm, code: str | None):
    monkeypatch.setenv("DATA_FILE", str(tmp_path / "db.json"))
    monkeypatch.setenv("LLM_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("MONGODB_URI", "")
    monkeypatch.setenv("VERCEL", "")
    monkeypatch.setenv("ACCESS_CODE", code or "")
    monkeypatch.setenv("PUBLIC_DEMO", "1")
    monkeypatch.setenv("SIM_DEMO_FIXTURES", "on")
    from backend.app import config, llm, storage

    config.get_settings.cache_clear()
    storage.get_store.cache_clear()
    llm.get_client.cache_clear()
    from backend.app.main import app

    client = TestClient(app)
    client.fake = fake_llm  # type: ignore[attr-defined]
    return client, app


@pytest.fixture()
def public(monkeypatch, tmp_path, fake_llm):
    client, app = _client(monkeypatch, tmp_path, fake_llm, CODE)
    yield client, app
    from backend.app import config, llm, storage

    config.get_settings.cache_clear()
    storage.get_store.cache_clear()
    llm.get_client.cache_clear()


def _api_routes(app):
    """Every documented /api route and method (the OpenAPI schema lists routes from included routers too)."""
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/api"):
            for method in ops:
                yield method.upper(), path


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "abc123", path)


def test_every_write_and_every_unlisted_read_needs_the_code(public):
    client, app = public
    routes = list(_api_routes(app))
    assert len(routes) > 60
    for method, path in routes:
        url = _fill(path)
        r = client.request(method, url, json={})
        if path in OPEN_PATHS:
            continue
        if method == "GET" and any(p.match(url) for p in VISITOR_GET):
            assert r.status_code != 401, (method, path)
        else:
            assert r.status_code == 401, (method, path, r.status_code)
    assert client.fake.calls == []


def test_credit_spending_routes_are_closed_without_the_code(public):
    client, _ = public
    for url in ("/api/candidates/demo", "/api/candidates/x/insights", "/api/candidates/x/forecast",
                "/api/candidates/x/recommendations", "/api/candidates/x/events/tag",
                "/api/sim/populations", "/api/sim/runs/panel", "/api/sim/runs/social", "/api/sim/runs/survey",
                "/api/sim/runs/x/step", "/api/sim/runs/x/summarize", "/api/sim/runs/x/branch"):
        assert client.post(url, json={}).status_code == 401, url
        assert client.post(url, json={}, headers={"x-access-code": "wrong"}).status_code == 401, url
    assert client.fake.calls == []


def test_visitors_see_demos_and_validation_only(public):
    client, _ = public
    meta = client.get("/api/meta").json()
    assert meta["public_demo"] is True and meta["access_required"] is True
    assert client.get("/api/candidates").status_code == 401
    assert client.get("/api/auth/check").status_code == 401

    # with the code: a private population that visitors must not see
    full = {"x-access-code": CODE}
    private = client.post("/api/sim/populations", json={"name": "Private", "size": 20, "persona_mode": "demographic", "seed": 1},
                          headers=full).json()
    assert client.get(f"/api/sim/populations/{private['id']}", headers=full).status_code == 200
    assert client.get(f"/api/sim/populations/{private['id']}").status_code == 404
    assert client.get(f"/api/sim/populations/{private['id']}/agents").status_code == 404

    pops = client.get("/api/sim/populations").json()
    assert pops and all(p.get("demo") for p in pops)
    runs = client.get("/api/sim/runs").json()
    assert all(r.get("demo") for r in runs)
    assert any(p["id"] == private["id"] for p in client.get("/api/sim/populations", headers=full).json())

    if runs:  # the demo fixture is present
        rid = runs[0]["id"]
        assert client.get(f"/api/sim/runs/{rid}").status_code == 200
        assert client.post(f"/api/sim/runs/{rid}/step").status_code == 401
        assert client.delete(f"/api/sim/runs/{rid}").status_code == 401
    v = client.get("/api/validation")
    assert v.status_code in (200, 404)  # 404 only if no validation fixture is committed
    assert client.fake.calls == []


def test_public_demo_without_a_code_is_read_only_for_everyone(monkeypatch, tmp_path, fake_llm):
    client, _ = _client(monkeypatch, tmp_path, fake_llm, None)
    try:
        assert client.post("/api/sim/estimate", json={"kind": "populate", "config": {}}).status_code == 401
        assert client.post("/api/candidates", json={"name": "x"}).status_code == 401
        assert client.get("/api/sim/meta").status_code == 200
    finally:
        from backend.app import config, storage

        config.get_settings.cache_clear()
        storage.get_store.cache_clear()
