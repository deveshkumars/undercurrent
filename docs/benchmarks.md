# Benchmarks

Every number on this page was measured, not estimated: `scripts/benchmark.py` wraps each model call and logs the usage the model backend reported and the call's latency. Regenerate with the command below; the raw summary is in [benchmarks.json](benchmarks.json).

## 1,000-agent, 3-arm message test

Run 2026-10-11: `LLM_BACKEND=claude-cli SIM_CONCURRENCY=12 .venv/bin/python scripts/benchmark.py `  
Model `claude-haiku-5-5` via `claude-cli`, 12 calls at a time; arms: No ad (placebo news), Savings, Comfort; 7 questions (product questionnaire); one structured call per agent per arm, the control first so it writes the agent's persona to the prompt cache and the other arms read it.

| | Message test (agent calls) | Including the debrief |
|---|---|---|
| Wall time | 25.2 min | |
| Calls (failed) | 3,000 (0) | 3,001 (0) |
| Throughput | 125.6 calls/min | |
| Latency p50 / p95 | 3.71 s / 5.61 s | |
| Input tokens: uncached | 6,048 | 6,050 |
| Input tokens: cache write (of which 1-hour) | 6,131,868 (6,131,868) | 6,145,693 (6,145,693) |
| Input tokens: cache read | 10,205,932 | 10,205,932 |
| Output tokens | 1,604,597 | 1,621,364 |
| Prompt-cache hit rate (share of input tokens read from cache) | 62.5% | 62.4% |
| Calls that read from the cache | 99.6% | |
| API-equivalent cost | $2.13 | $2.14 |

Building the 1,000 interview personas (one call each, a one-time cost per population): 1,000 calls (0 failed), 57.4 min, 4,617,827 output tokens, $2.69 API-equivalent.

### Reading it

- The pre-run estimate (API path) was 3,001 calls and $0.93; measured cost was $2.13. Through the claude-cli shim each call carries Claude Code's own overhead (1-hour cache writes billed at 2x input, and an extra turn for structured output), so the direct API path should come in below the measured figure. Nothing was billed per token: the shim runs on the Claude Code subscription.
- Almost every call reads something from the cache (99.6%): the system prompt is shared by all agents, and each agent's persona is written by its control call and read by its other two arms. The token hit rate (62.5%) is lower because the persona has to be written once per agent (and the CLI also caches each call's tail, which adds writes that are never read).
- The step protocol held at this size: the run recorded 3,001 calls, matching the 3,001 logged call by call, with 0 failed responses and one stored result per agent and arm. The measured effect on purchase intent (0–100) for Savings vs the control was 12.33 [11.29, 13.49] on 1,000 paired agents.
