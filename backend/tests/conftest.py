import pytest
from fastapi.testclient import TestClient

from .fakes import FakeLLM


@pytest.fixture()
def fake_llm(monkeypatch):
    from backend.app import llm

    fake = FakeLLM()
    monkeypatch.setattr(llm, "structured", fake)
    return fake


@pytest.fixture()
def sim_client(tmp_path, monkeypatch, fake_llm):
    monkeypatch.setenv("DATA_FILE", str(tmp_path / "db.json"))
    monkeypatch.setenv("LLM_BACKEND", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("MONGODB_URI", "")
    monkeypatch.setenv("ACCESS_CODE", "")
    monkeypatch.setenv("VERCEL", "")
    monkeypatch.setenv("SIM_CONCURRENCY", "4")
    monkeypatch.setenv("SIM_STEP_SECONDS", "30")
    from backend.app import config, llm, storage

    config.get_settings.cache_clear()
    storage.get_store.cache_clear()
    llm.get_client.cache_clear()
    from backend.app.main import app

    client = TestClient(app)
    client.fake = fake_llm  # type: ignore[attr-defined]
    yield client
    config.get_settings.cache_clear()
    storage.get_store.cache_clear()
    llm.get_client.cache_clear()


def drive(client, rid: str, max_steps: int = 200) -> dict:
    """Step a run until it stops."""
    run = client.get(f"/api/sim/runs/{rid}").json()
    for _ in range(max_steps):
        if run["status"] in ("done", "failed", "canceled", "paused", "budget_exhausted"):
            return run
        r = client.post(f"/api/sim/runs/{rid}/step")
        assert r.status_code == 200, r.text
        run = r.json()
    raise AssertionError(f"run did not finish: {run['status']}")
