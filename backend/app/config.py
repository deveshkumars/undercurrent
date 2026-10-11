"""Runtime configuration, read once from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Minimal .env loader so local dev needs no extra dependency. Real env vars win."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


@dataclass(frozen=True)
class Settings:
    # "anthropic" calls the real Messages API; "claude-cli" points the same SDK at the local shim.
    llm_backend: str
    llm_model: str
    llm_effort: str
    llm_max_tokens: int
    anthropic_api_key: str | None
    claude_cli_shim_url: str

    mongodb_uri: str | None
    mongodb_db: str
    data_file: Path

    access_code: str | None
    # read-only public demo: visitors without the code can view saved demo runs and validation results
    public_demo: bool
    on_vercel: bool

    # Simulations (backend/app/sim). Agents default to the app's model; SIM_MODEL can pin a cheaper one.
    sim_model: str
    sim_concurrency: int
    sim_step_seconds: float
    sim_call_timeout: float
    sim_max_agents: int
    sim_max_social_agents: int
    sim_max_calls_per_run: int
    sim_agent_effort: str
    sim_agent_thinking: str  # "off" | "adaptive"
    sim_price_in: float | None  # USD per million input tokens; None = built-in table
    sim_price_out: float | None

    @property
    def storage_backend(self) -> str:
        return "mongodb" if self.mongodb_uri else "json-file"

    @property
    def sim_enabled(self) -> bool:
        # On Vercel the JSON store is per-instance /tmp, so step calls can't share run state.
        return not (self.on_vercel and self.storage_backend == "json-file")


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
    on_vercel = bool(os.environ.get("VERCEL"))
    default_data_file = Path("/tmp/undercurrent.json") if on_vercel else ROOT / "data" / "undercurrent.json"
    llm_backend = os.environ.get("LLM_BACKEND", "anthropic").strip().lower()
    llm_model = os.environ.get("LLM_MODEL", "claude-haiku-5-5")
    cli = llm_backend == "claude-cli"

    def _float(name: str) -> float | None:
        raw = os.environ.get(name, "").strip()
        return float(raw) if raw else None

    return Settings(
        llm_backend=llm_backend,
        llm_model=llm_model,
        llm_effort=os.environ.get("LLM_EFFORT", "medium"),
        llm_max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "32000")),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        claude_cli_shim_url=os.environ.get("CLAUDE_CLI_SHIM_URL", "http://127.0.0.1:8788"),
        mongodb_uri=os.environ.get("MONGODB_URI") or None,
        mongodb_db=os.environ.get("MONGODB_DB", "undercurrent"),
        data_file=Path(os.environ.get("DATA_FILE", str(default_data_file))),
        access_code=os.environ.get("ACCESS_CODE") or None,
        public_demo=os.environ.get("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes", "on"),
        on_vercel=on_vercel,
        sim_model=os.environ.get("SIM_MODEL") or llm_model,
        sim_concurrency=int(os.environ.get("SIM_CONCURRENCY") or (3 if cli else 12)),
        sim_step_seconds=float(os.environ.get("SIM_STEP_SECONDS") or (150 if on_vercel else 45)),
        sim_call_timeout=float(os.environ.get("SIM_CALL_TIMEOUT") or (300 if cli else 90)),
        sim_max_agents=int(os.environ.get("SIM_MAX_AGENTS", "500")),
        sim_max_social_agents=int(os.environ.get("SIM_MAX_SOCIAL_AGENTS", "200")),
        sim_max_calls_per_run=int(os.environ.get("SIM_MAX_CALLS_PER_RUN", "5000")),
        sim_agent_effort=os.environ.get("SIM_AGENT_EFFORT", "low"),
        sim_agent_thinking=os.environ.get("SIM_AGENT_THINKING", "off"),
        sim_price_in=_float("SIM_PRICE_IN"),
        sim_price_out=_float("SIM_PRICE_OUT"),
    )
