# AGENTS.md

This file provides guidance to coding agents (Claude Code and others) when working with code in this repository.

Undercurrent is a public-opinion simulator (test messages, products and policies on simulated audiences) with campaign analysis as one section: FastAPI backend (`backend/app`) + React/Vite/TypeScript frontend (`frontend/src`), deployed to Vercel at undercurrent.deveshkumar.net with MongoDB Atlas storage. It aligns a candidate's polls with their events, measures event impacts, and uses Claude (`claude-haiku-5-5` by default) for insights, forecasts and strategy.

## Commands

```bash
make setup      # uv venv (.venv, Python 3.12) + pip install requirements-dev.txt + npm install in frontend/
make dev        # backend :8010 (reload) + Vite :5173 (proxies /api → :8010); uses ANTHROPIC_API_KEY from .env
make dev-cli    # same, plus the claude-CLI shim on :8788 and LLM_BACKEND=claude-cli (no API key needed)
make api        # backend only     make web   # frontend only     make shim   # shim only
make serve      # build frontend, serve everything from FastAPI on :8010
make test       # .venv/bin/python -m pytest backend/tests -q
make build      # frontend: tsc --noEmit && vite build (this is the only type check / lint step)
```

Single test: `.venv/bin/python -m pytest backend/tests/test_analytics.py::test_demo_effects_are_recovered -q`

- The API runs on **8010**, not 8000 (8000 is used by another app on this machine).
- There is no Python linter/formatter or ESLint configured.
- Tests never call a model: `test_api.py` isolates config via env vars (`DATA_FILE` → tmp, empty `ANTHROPIC_API_KEY`/`MONGODB_URI`/`ACCESS_CODE`) and clears the `lru_cache`d `get_settings`, `get_store`, `get_client`. Follow the same pattern in new API tests, since `config.py` otherwise loads the developer's real `.env`.
- API docs at http://localhost:8010/api/docs. `.claude/launch.json` defines `web` (Vite on 5173), `api` (uvicorn on 8010 with `LLM_BACKEND=claude-cli`, also serves the built UI from `frontend/dist`) and `shim` (8788).

## Architecture

**Request flow.** All routes are in `backend/app/main.py` under `/api`. `public` router: `/health`, `/meta`. `api` router: everything else. `access.AccessMiddleware` classifies every request as full (valid `X-Access-Code`, or no `ACCESS_CODE` configured and `PUBLIC_DEMO` off), visitor (`PUBLIC_DEMO=1`, a GET on the read-only allowlist in `access.VISITOR_GET`; sim routes then only return `demo: True` documents) or 401; `require_access` re-checks behind it. The frontend stores the code in localStorage and re-prompts on 401; visitors get a read-only UI (`readOnly.ts`). Any new GET route visitors may see must be added to `VISITOR_GET` and scope its data; `test_access.py` walks every route. Data is scoped per candidate: `/api/candidates/{cid}/polls|events|analysis|insights|forecast|recommendations|reports`.

**Numbers are deterministic; the model only interprets them.** `analytics.analyze(polls, events, metric, segment, window)` is the core: selects polls → house-effect adjustment → causal inverse-variance average (7-day half-life) → per-event before/after impact with SE, z-score and signal label (also per segment) → pooled topic (`themes`) and format (`event_types`) effects. `find_analogs` builds the forecast prior. The README's "How the numbers work" section documents the methodology; keep it in sync if constants in `analytics.py` change. `test_demo_effects_are_recovered` checks that analysis recovers the effects planted in `sample_data.py` (correlation > 0.7), so changes to the estimator or the demo data must keep that passing.

**AI pipeline.** Each AI route: `_analysis(...)` → `prompts.build_dossier(candidate, analysis)` (a long markdown summary of polls, events with quotes, impacts) → `llm.structured(task, OutputModel, dossier)` → `_save_report(...)` stores a `Report` (kind, params, quant incl. token usage, output) in the `reports` collection. Details that span files:
- `llm.structured` makes one streamed Messages API call with `output_format=<pydantic model>` (structured outputs) and `output_config.effort`. The dossier is sent as the first content block with `cache_control` so successive features reuse the cached prefix; the task prompt comes after it. Errors are mapped to `LLMError` (status code + user-facing message), rendered by an exception handler in `main.py`.
- Forecast is two calls: `features_task` (low effort, extracts topics/format from the draft) → `analytics.find_analogs` computes the statistical prior → `forecast_task` asks the model to adjust that prior. Event tagging (`/events/tag`) is a single low-effort call with no dossier.
- `SYSTEM_PROMPT` in `prompts.py` carries the analytical and ethical rules (correlational framing, cite quotes, no deceptive tactics, nonpartisan).
- Output schemas live in `backend/app/ai_schemas.py` and are **mirrored by hand** in `frontend/src/types.ts` (`InsightsOutput`, `ForecastOutput`, `RecommendationsOutput`, …). Change both together, then update the matching view in `frontend/src/views/`.

**LLM backends.** The app always uses the official Anthropic SDK. `LLM_BACKEND=claude-cli` only changes `base_url` to `shim/claude_cli_api.py`, a FastAPI app that implements the subset of `POST /v1/messages` Undercurrent uses (system, text, `output_config.format` → `claude -p --json-schema`, effort, SSE streaming replayed from the finished result) by spawning a fresh tool-less `claude -p` from an empty temp dir. It's local-testing only and excluded from the Vercel bundle. If you start sending new request features (tools, images, new content block types), the shim must be extended or it will reject/ignore them; `test_shim.py` covers it with a fake CLI process.

**Storage.** `storage.get_store()` returns `MongoStore` if `MONGODB_URI` is set, else `JsonFileStore` (`data/undercurrent.json`, or `/tmp` on Vercel, which is ephemeral). Both implement the same `Store` protocol over plain dicts keyed by string `id` (Mongo also sets `_id = id` and strips `_id` on read). Collections: `candidates`, `polls`, `events`, `reports` in `DATA_FILE`, plus the simulation collections (`populations`, `agents`, `sim_runs`, `sim_results`, `sim_state`, `sim_ticks`, `sim_checkpoints`, `sim_posts`), each in its own `data/undercurrent.<collection>.json`. Filtering is equality-only via kwargs; `sort="-field"` for descending; `fields=` projects, `limit`/`skip` page; `update_if` is compare-and-set and `upsert_many` is idempotent. Use only that interface from routes so both backends keep working.

**Models.** `models.py` uses `XIn` (request body) / `X` (stored, adds `id`, `candidate_id`, timestamps) pairs; routes store `X(...).model_dump(mode="json")`. Polls have `metric` (default `vote_share`) and `segment` (default `All`; other values are crosstabs). CSV import (`importers.py`) matches headers loosely via alias tables.

**Frontend.** Single `App.tsx` with hash routing in three areas: `#/` and `#/sim/...` (Simulations, the home page, in `frontend/src/sim/`), `#/campaigns/<candidateId>/<tab>` (tabs: overview, insights, forecast, strategy, simulate, data; old `#/<candidateId>/<tab>` links redirect here), and `#/validation` (`sim/ValidationView.tsx`). All HTTP goes through `api.ts` (`request()` adds the access code and turns FastAPI `detail` into `ApiError`). `views/useReports.ts` loads and selects saved reports per kind. Charts are hand-built SVG (`components/PollChart.tsx`, `MiniCharts.tsx`); there's no chart library. Styling is plain CSS in `styles.css`.

**Deployment (Vercel).** `vercel.json` builds the frontend to `frontend/dist`, runs `api/index.py` (imports `backend.app.main:app`) as a Python function with `maxDuration: 300` (AI calls take 20–90 s), and rewrites `/api/*` to it and everything else to `index.html`. `.vercelignore` excludes `shim/`, `backend/tests/`, `scripts/` and `data/`. Production needs `ANTHROPIC_API_KEY`, `MONGODB_URI` and (recommended) `ACCESS_CODE`. DNS for the subdomain is a GoDaddy CNAME to `cname.vercel-dns.com` (see README). Ask before creating Vercel projects, Atlas clusters or DNS records.

**Simulations (`backend/app/sim/`).** LLM-agent populations, after Park et al. 2024 (interview + four-expert-reflection agents; message tests) and POSIM 2026 (Social-BDI agents on a feed driven by a Hawkes process). Conventions:
- Runs are stepped by the browser: `POST /api/sim/runs/{id}/step` → `runner.step` claims a lease (`update_if` on `version`), runs batches on a thread pool until `SIM_STEP_SECONDS`, upserts results under deterministic ids, releases. Each run kind has a module with `step(ctx)` / `finalize(ctx)` (`jobs` populate, `panel` panel+calibration, `candidate` backtest, `social`, `survey` closed-ended questionnaires). Handlers write results through `ctx.save(...)` (refuses once the lease is lost, so a late step never overwrites a takeover's results; its spend is still recorded in `release`). Never do run work outside this protocol (scripts drive it in-process with `scripts/runs.py:drive`, always on a local JSON store); on Vercel a JSON store can't share state, so sims return 503 without `MONGODB_URI`.
- Validation (`sim/validation.py`, `scripts/validate.py`, `scripts/experiments.py`) scores survey runs against OpinionQA / Pew ATP data that `scripts/fetch_opinionqa.py` downloads to `data/opinionqa/` (gitignored; never commit raw or per-group distributions). Results are committed as `backend/app/sim/fixtures/validation.json` / `experiments.json` and rendered into `docs/validation.md` (`scripts/validate.py --render-docs`); never hand-edit those numbers.
- Built-in demos: `scripts/seed_demos.py` runs the two fictional demo scenarios and exports `backend/app/sim/fixtures/demo.json.gz`; `sim/demo.py` upserts it (docs flagged `demo: True`) on the first sim request of a process. Tests turn this off with `SIM_DEMO_FIXTURES=off` (set in `conftest.py`).
- Sim code calls `llm.structured` through the module (`from .. import llm`), so tests can monkeypatch it; `backend/tests/fakes.py` is a fake LLM with planted effects. Every new sim feature needs a test that runs offline with it.
- Agent calls send `system=` + `cache_system=True` + a cached persona `Block`; keep system prompts in `sim/prompts.py` byte-stable and use one output schema per run (`make_panel_schema` named `PanelAnswers`), or the prompt cache stops hitting. No temperature: Haiku 5.5 rejects it.
- Deterministic math (sampling, raking, bootstrap, Hawkes, feed ranking, emotion dynamics) is pure Python in `demographics.py`, `metrics.py`, `hawkes.py`, `feed.py`, `dynamics.py`; the model only plays the people. Sim types are mirrored by hand in `frontend/src/sim/types.ts`.
- Agents must not see poll numbers (they'd anchor calibration). Results pages show caveats: synthetic personas ≈ Park's demographic baseline, intervals measure simulation noise only, LLM effects run large (backtests rescale them via β on the thermometer).
