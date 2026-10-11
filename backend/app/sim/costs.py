"""Rough call, token, dollar and wall-clock estimates, shown before a run starts and tracked during it."""

from __future__ import annotations

import math

from ..config import get_settings

# USD per million tokens (input, output) for prompts up to 100K tokens.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-fable-5-1": (10.00, 50.00),
}

# Typical seconds per call, used only for the time estimate.
LATENCY = {"persona": 30.0, "reflections": 12.0, "panel": 6.0, "social": 7.0, "summary": 30.0}
CLI_FACTOR = 3.0  # each shim call is a fresh `claude -p` process


def prices(model: str | None = None) -> tuple[float, float]:
    s = get_settings()
    base = PRICES.get(model or s.sim_model)
    if base is None:
        base = next((v for k, v in PRICES.items() if (model or s.sim_model).startswith(k)), PRICES["claude-sonnet-5-5"])
    return (s.sim_price_in or base[0], s.sim_price_out or base[1])


def usd(usage: dict, model: str | None = None) -> float:
    """List-price dollars for a usage dict. Cache writes: 1.25x input (5-minute TTL), 2x (1-hour);
    ``cache_creation_1h_input_tokens`` is the 1-hour part of ``cache_creation_input_tokens``."""
    p_in, p_out = prices(model)
    writes = usage.get("cache_creation_input_tokens", 0)
    writes_1h = min(writes, usage.get("cache_creation_1h_input_tokens", 0))
    return (
        usage.get("input_tokens", 0) * p_in
        + (writes - writes_1h) * 1.25 * p_in
        + writes_1h * 2.0 * p_in
        + usage.get("cache_read_input_tokens", 0) * 0.1 * p_in
        + usage.get("output_tokens", 0) * p_out
    ) / 1e6


def _pack(calls: int, inp: float, cached: float, out: float, kind: str, extra_seconds: float = 0) -> dict:
    s = get_settings()
    usage = {"input_tokens": inp, "cache_read_input_tokens": cached, "output_tokens": out}
    latency = LATENCY[kind] * (CLI_FACTOR if s.llm_backend == "claude-cli" else 1.0)
    minutes = (calls * latency / max(1, s.sim_concurrency) + extra_seconds) / 60
    return {
        "calls": int(calls),
        "input_tokens": int(inp + cached),
        "output_tokens": int(out),
        "usd": round(usd(usage), 4),
        "minutes": round(minutes, 1),
        "model": s.sim_model,
        "backend": s.llm_backend,
        "billing": "subscription (claude-cli)" if s.llm_backend == "claude-cli" else "api",
    }


def persona_tokens(transcript_words: int, per_expert: int) -> int:
    return int(transcript_words * 1.35 + per_expert * 4 * 32 + 250)


def estimate_populate(n: int, persona_mode: str, transcript_words: int = 900, per_expert: int = 6, imported: bool = False) -> dict:
    if persona_mode == "demographic" and not imported:
        return _pack(0, 0, 0, 0, "persona")
    if imported:
        return _pack(n, n * 1800, 0, n * (per_expert * 4 * 32 + 150), "reflections")
    return _pack(n, n * 900, 0, n * persona_tokens(transcript_words, per_expert), "persona")


def estimate_panel(n: int, arms: int, replicates: int, n_questions: int, persona_tok: int, stim_tokens: int) -> dict:
    calls = n * arms * replicates
    first = n  # first call per agent writes the persona cache; the rest read it
    tail = 250 + stim_tokens + n_questions * 45
    inp = first * (900 + persona_tok) + calls * tail
    cached = (calls - first) * (900 + persona_tok)
    out = calls * (110 + n_questions * 18)
    est = _pack(calls + 1, inp + 6000, cached, out + 2500, "panel", extra_seconds=LATENCY["summary"])
    return est


def estimate_social(n_agents: int, hours: int, tick_minutes: int, max_calls_per_tick: int, persona_tok: int = 900) -> dict:
    ticks = math.ceil(hours * 60 / tick_minutes)
    # Hawkes: baseline ~1%/agent-hour plus bursts after events; cap per tick bounds it.
    expected = min(ticks * max_calls_per_tick, int(n_agents * (0.6 + 0.04 * hours) + ticks * 0.3))
    calls = max(1, expected)
    inp = calls * (1800 + 10 * 90)
    cached = calls * persona_tok
    out = calls * 260
    return _pack(calls, inp, cached, out, "social")
