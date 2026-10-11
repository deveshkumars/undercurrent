# Undercurrent

**Test messages on simulated audiences before you ship them.**

Undercurrent builds populations of AI agents modeled on different kinds of people, shows them a message, product, policy or crisis response, and measures who moves and why. It can also drop a news event onto a simulated social feed and test responses to it (an apology, a fact-check, a ranking change) against a no-change control from the same moment.

- **Message tests**: a control and up to four versions of an ad, pitch, policy or statement, each shown to the same simulated people in separate calls, so effects are paired. Weighted toplines, effects with bootstrap intervals, effects by segment, quotes, and a debrief written from those numbers.
- **Social scenarios**: a seed event lands on a follower network; a Hawkes process decides who opens the app, each agent reads a ranked feed and reacts. Branch from any hour to test interventions.
- **Populations**: stratified synthetic samples (U.S. adults, registered or likely voters, or your own margins), raked to their targets, with model-written life-history interviews, or real respondents imported from a CSV.
- **Validation**: how the agents score against real people's answers to real survey questions, and against classic survey experiments. See [Validation](#validation).
- **Campaigns**: the original campaign-analysis tools (polling average, event impacts, forecasts and strategy for a candidate) are one use case, in their own section. See [Campaigns](#campaigns).

The built-in demos use fictional brands: a smart-thermostat launch test (a control and three ads on 150 simulated U.S. adults) and a kettle-recall crisis (80 accounts over 12 simulated hours, branched two hours in into an apology, a transparency response and a no-change control). They are saved runs, so they open without an API key: `scripts/seed_demos.py` generated them on 2026-10-11 with Claude Haiku 5.5 through the Claude Code CLI (1,044 calls, $1.29 API-equivalent) and exported `backend/app/sim/fixtures/demo.json.gz`, which loads into the store on first use.

## What simulations can and can't tell you

Use them to compare options and catch risks early, not as a poll.

- **They agree with each other more than real people do.** Against 100 real Pew American Trends Panel questions (OpinionQA), simulated populations did not beat a uniform-random guess (representativeness 0.806–0.824 vs 0.820 for random; Claude Haiku 5.5 via the Claude Code CLI, 2026-10-11), mainly because simulated answers pile onto one option: the most common answer got 74–80% among agents against 55% among real respondents. Simulated groups also differ less than real groups. Details and the exact runs: [docs/validation.md](docs/validation.md).
- **Comparisons hold up better than levels.** In replications of classic survey experiments, every effect with a published reference came out in the right direction (framing, question wording, anchoring, sunk cost), but sizes ranged from 0.02× to 2.3× the published effect. Agents also knew the answers to factual anchoring questions, which flattened those effects.
- **Intervals measure simulation noise only** (which agents, which model draw), not whether the agents resemble real people.
- **LLM agents overreact to messages and can stereotype groups.** Message-test effects run larger than real persuasion effects; backtests (campaign hooks) rescale them.
- **Synthetic interviews add detail, not information.** The interviews are written by the model from a demographic card. Agents built from real people's interviews or survey answers (CSV import) are the higher-fidelity path; they were not part of the validation runs above.

The deployed version uses **Claude Haiku 5.5** (`claude-haiku-5-5`). For local testing, you can route the same requests to the **Claude Code CLI** through a small FastAPI shim, so no API key is needed.

## Quick start

```bash
make setup
cp .env.example .env     # then add ANTHROPIC_API_KEY, or use the CLI shim below
make dev                 # API on :8010, UI on http://localhost:5173
```

The app opens on **Simulations**, with the two demo scenarios. **Campaigns** has a fictional governor's race (**Explore a demo campaign**) with synthetic polls in which known effects were planted at each event, so you can check that the analysis recovers them.

### Testing with the Claude Code CLI instead of an API key

```bash
make dev-cli
```

This starts `shim/claude_cli_api.py` on `:8788` and runs the backend with `LLM_BACKEND=claude-cli`. The shim implements the part of `POST /v1/messages` that Undercurrent uses: system prompt, text messages, structured outputs (`output_config.format` → `claude -p --json-schema`), `effort`, and streaming (it replays the finished result as the same SSE events the API sends). The app keeps using the official Anthropic SDK; only `base_url` changes. Each request runs as a fresh `claude -p` with tools, MCP servers and your customizations turned off (`--tools "" --safe-mode`), from an empty working directory. It uses whatever account `claude` is logged into.

A single user turn is passed as stream-json with its content blocks intact, so cache breakpoints reach the API and a cached persona is read by the agent's later calls. Two differences from the direct API path show up in usage: the CLI writes 1-hour cache entries (billed at 2× input instead of 1.25×; breakpoints are sent with `ttl: 1h` to match), and it satisfies `--json-schema` through an internal tool call, which adds output tokens and a second turn. Usage, including the 1-hour/5-minute cache-write split, is passed through, and cost estimates price it accordingly.

You can run the shim on its own and point any Anthropic SDK client at it:

```bash
make shim
```

```python
client = anthropic.Anthropic(api_key="unused", base_url="http://127.0.0.1:8788")
```

Shim settings: `SHIM_MODEL` (force a model for every request, e.g. `sonnet`), `SHIM_TIMEOUT` (seconds, default 300), `SHIM_MAX_CONCURRENCY` (default 3), `CLAUDE_BIN`. The shim is for testing only: no client tools and no images, and multi-turn histories are flattened into a transcript.

## Simulations

Simulations is the home page; a candidate's **Simulate** tab opens the same tools with campaign hooks. The engine is general: any stimulus (an ad, a speech, a product pitch, a policy) and any questions. Candidate hooks add calibration and backtests.

The design follows two papers:

- **Park et al. (2024), *Generative Agent Simulations of 1,000 People*** (Stanford HAI). Each agent is the model given one person's life-history interview plus notes written from four expert perspectives (psychologist, behavioral economist, political scientist, demographer). Agents built from real two-hour interviews reproduced people's General Social Survey answers 83% as well as the people reproduced their own answers two weeks later; agents built from their survey answers reached 82%, and demographics alone 74% (arXiv 2411.10109 v3; the first version reported 85% for interviews and 71% for demographics).
- **POSIM (2026), a multi-agent simulator of public-opinion dynamics on social media.** Agents run a Belief → Desire → Intention loop with irrational factors (confirmation bias, herd behavior, emotional contagion), on a follower network with a personalized feed, and a Hawkes process decides when they're active. Interventions branch from checkpoints.

### Populations

- **Synthetic**: a stratified sample from U.S. adult, registered-voter or likely-voter margins (rounded Census/Pew figures) that you can override for a place, e.g. a district's party mix. Child variables are drawn from conditional tables tilted to hit the targets, then raking makes the survey weights match every margin exactly (weights trimmed to 0.2–5× the mean). Each agent gets a seeded trait layer (Big Five, occupation, news diet, issues, POSIM psychological type, social-media activity), then one model call writes an interview transcript and the four experts' notes. "Card only" skips the model entirely: Park's weaker baseline, instant and free.
- **Imported**: a CSV with one row per real respondent. Recognized demographic columns fill the card (missing values stay unknown), a weight column seeds the weights, name/email/phone/address/ZIP/IP/birth-date columns are dropped, and every other column becomes a survey answer the agent remembers (or an `interview` column becomes the transcript). This is the higher-fidelity path; synthetic interviews add fluency, not information about real people.

### Message tests

Every agent answers the questionnaire once under the control (neutral local news, or nothing) and once under each message version, in separate calls, so effects are paired within the same simulated people. Questions come from a political, product or policy preset plus your own; each question is routed to the expert whose notes are most relevant. Results: weighted toplines, paired effects with 95% bootstrap intervals, effects by segment (with a Benjamini–Hochberg false-discovery flag and small groups grayed), vote transitions, quotes, and a debrief written from those numbers.

### Calibration and backtests (candidate hooks)

- **Calibration** asks every agent how they'd vote today with no message, compares the weighted split with the candidate's house-adjusted polling average overall and in each poll segment (labels like "Independents", "Women", "Under 35", "Hispanic women 18-29" are parsed), and can rake a second weight set to match.
- **Backtests** replay past events with measured poll movement, giving agents only the news up to the day before, and fit *measured ≈ β × simulated* through the origin. Later message tests for that candidate show backtest-adjusted vote-share effects, since LLM agents overreact.

### Social scenarios

A seed event lands on a follower network (homophily plus preferential attachment, ~5% opinion leaders, left/center/right outlets, an official account). Each 10-minute tick, λ(t) = μ·circadian(t) + exogenous and endogenous exponential kernels sets how many agents open the app (POSIM's parameters, with the endogenous jump rescaled so the branching ratio stays 0.9 for a small network); each active agent gets a ranked feed (0.3 homophily + 0.3 popularity + 0.4 freshness, 20% exploration), and one structured call returns perception, updated opinions and emotions, a motive, and 0–2 actions. Emotions decay toward each agent's baseline and spread by contagion. The run tracks activity, the negative emotion ratio, emotional concentration, stance by party and cascades; click any hour to branch with an intervention (apology, transparency, fact-check, rational or empathy priming, a ranking change) alongside a no-change control.

### Running and cost

Runs advance in steps driven by the open browser tab (`POST /api/sim/runs/{id}/step`): each step claims a lease, makes calls in parallel until its time budget is spent, and saves results under fixed ids, so it works on a 300-second serverless function and a second tab just watches. Estimates are shown before you start. Measured on Haiku 5.5 through the CLI shim with 12 calls at a time (2026-10-11, recorded in [docs/validation.md](docs/validation.md)): 400 interview personas took 24.5 minutes and $1.04 of API-equivalent usage (about 25 s per persona), and 4,000 ten-question survey calls took 22–39 minutes and $2.25–2.94. The CLI path uses more tokens than the direct API (1-hour cache writes and an extra structured-output turn), so the same work through the API should cost less; the estimates shown in the app are for the API. On Vercel, simulations require `MONGODB_URI`.

Treat results as a way to compare messages and find risks, not as a poll: intervals measure simulation noise only, and LLM agents can stereotype groups and overreact to messages.

## Validation

**Validation** in the top bar shows how closely simulated respondents reproduce real Americans' answers to real survey questions: Pew American Trends Panel questions from [OpinionQA](https://github.com/tatsu-lab/opinions_qa) (Santurkar et al., 2023) on technology, science, health, the economy and daily life, scored with OpinionQA's representativeness metric overall and for 27 demographic groups. It compares interview agents, card-only agents, a demographics-only prompt, a uniform-random baseline, the real topline used for every group, and the finite-sample ceiling. Classic survey experiments (gain/loss framing, allowed/forbidden wording, anchoring, sunk cost, plus paraphrases) are replicated as message tests next to their Many Labs 1 results. Method, results and the exact runs are in [docs/validation.md](docs/validation.md).

```bash
.venv/bin/python scripts/fetch_opinionqa.py         # the raw Pew data is downloaded, never committed
.venv/bin/python scripts/validate.py --dry-run      # cost estimate
LLM_BACKEND=claude-cli SIM_CONCURRENCY=12 .venv/bin/python scripts/validate.py --split test
LLM_BACKEND=claude-cli SIM_CONCURRENCY=12 .venv/bin/python scripts/experiments.py
```

The questions are asked through `survey` runs (`POST /api/sim/runs/survey`): closed-ended questionnaires in fixed-size blocks, one call per agent per block, with one output schema per run so the cached persona is reused.

## Campaigns

Campaign analysis lines up a candidate's polling with what they said and did, measures which actions moved the numbers, forecasts how a new speech or interview will land, and recommends what to do next. Open **Campaigns** in the top bar.

- **Overview**: a house-effect-adjusted polling average with every event plotted on it. Click an event to see the polls in the windows before and after it. Effects are pooled by topic and by format (debates, ads, interviews…).
- **Insights**: Claude reads the measured impacts and the candidate's actual words and explains what is driving the numbers, including language patterns that track with gains or losses.
- **Forecast**: paste a draft speech, interview prep or ad script. Undercurrent finds similar past events, computes a statistical prior from how polls moved after them, and Claude adjusts it line by line. You get an expected effect with a range, segment reactions, risky lines with rewrites, likely headlines and opponent attack lines.
- **Strategy**: priorities, messages to amplify or reframe, which formats to do more of, and a 30-day plan, all tied to the events they rest on.

### How the numbers work

All arithmetic lives in [`backend/app/analytics.py`](backend/app/analytics.py) and is deterministic. The model is given these numbers and is not asked to compute them.

- **Poll variance** = sampling error `p(100−p)/n` (n capped at 3,000) + a fixed 1.5-pt non-sampling error.
- **House effects**: each pollster's average residual against a leave-one-out average of *other* pollsters, shrunk toward zero and centered, then subtracted.
- **Polling average**: causal (no look-ahead) inverse-variance average with a 7-day half-life, so the value on a date uses only polls released by then.
- **Event impact**: inverse-variance mean of adjusted polls in the N days after the event minus the N days before (N defaults to 14 and can be changed in the UI), with a standard error and z-score. Signals: strong |z|≥2.58, clear ≥1.96, weak ≥1.28. Events whose windows overlap are flagged because credit is ambiguous. The same is computed per segment (crosstabs).
- **Topic / format effects**: inverse-variance pooling of event impacts.
- **Forecast prior**: similarity-weighted (topic overlap and format) pooling of the most similar past events, shrunk toward zero, with an 80% predictive range. Claude starts from this prior and must justify any move away from it.

These are correlations between events and polls, not causal estimates. A typical 2-week polling swing is shown on the dashboard so you can see how big an effect has to be before it is distinguishable from noise.

### Data

Add data in the **Data** tab, or import CSVs. Headers are matched loosely.

**Polls** (one row per topline or crosstab result): `date, pollster, sample_size, population, metric, segment, value, opponent_value, margin_of_error`. `date` and `value` are required. `metric` defaults to `vote_share` (use `approval`, `favorability`, etc. for other questions) and `segment` defaults to `All`; crosstab rows use the group name (`Independents`, `Women`, …).

**Events**: `date, type, title, summary, content, topics, tone, venue, audience, url`. `date` and `title` are required. `content` should hold what was actually said (quotes, transcript excerpts, the ad script), because the AI features read it. `topics` are separated by `;` or `|`. The **Suggest topics & tone** button in the event form tags an event with Claude.

Storage is a JSON file at `data/undercurrent.json` unless `MONGODB_URI` is set.

## Configuration

| Variable | Default | |
|---|---|---|
| `LLM_BACKEND` | `anthropic` | `claude-cli` sends requests to the shim |
| `ANTHROPIC_API_KEY` | | required when `LLM_BACKEND=anthropic` |
| `LLM_MODEL` | `claude-haiku-5-5` | |
| `LLM_EFFORT` | `medium` | `low` is faster; `high` is more thorough |
| `LLM_MAX_TOKENS` | `32000` | covers thinking + output; responses are streamed |
| `CLAUDE_CLI_SHIM_URL` | `http://127.0.0.1:8788` | |
| `MONGODB_URI` / `MONGODB_DB` | / `undercurrent` | required in production |
| `ACCESS_CODE` | | if set, the API requires it (the UI asks once) |
| `PUBLIC_DEMO` | off | `1`: visitors without the code can read the saved demo runs and the validation results; everything that writes or calls the model still needs `ACCESS_CODE` (with no code set, nobody can) |
| `SIM_DEMO_FIXTURES` | `on` | `off` skips loading the built-in demo scenarios |
| `SIM_MODEL` | `LLM_MODEL` | model for simulation agents |
| `SIM_CONCURRENCY` | `12` (`3` with the shim) | parallel calls per step |
| `SIM_STEP_SECONDS` | `45` (`150` on Vercel) | time budget per step |
| `SIM_MAX_CALLS_PER_RUN` | `5000` | hard cap per run |
| `SIM_MAX_AGENTS` / `SIM_MAX_SOCIAL_AGENTS` | `500` / `200` | |

## Deploying to undercurrent.deveshkumar.net

The repo is set up for Vercel: the Vite build is served statically and `api/index.py` runs the FastAPI app as a Python function (`vercel.json` rewrites `/api/*` to it).

1. **Database**: Vercel's filesystem is ephemeral, so use MongoDB Atlas (a free M0 cluster is plenty). Create a cluster and a database user, allow access from anywhere (`0.0.0.0/0`, since Vercel IPs vary), and copy the `mongodb+srv://…` connection string.
2. **Project and secrets** (each `vercel env add` prompts for the value, so secrets never go in the repo or your shell history):
   ```bash
   vercel link
   vercel env add ANTHROPIC_API_KEY production
   vercel env add MONGODB_URI production
   vercel env add ACCESS_CODE production     # required: the app spends your API credits
   vercel env add PUBLIC_DEMO production     # optional: "1" lets visitors browse the demos and validation read-only
   vercel --prod
   ```
   The demo scenarios load into MongoDB on the first simulation request; the validation results are served from the committed fixture.
3. **Domain**: `vercel domains add undercurrent.deveshkumar.net`, then add the CNAME at GoDaddy:
   ```bash
   gddy dns add deveshkumar.net --type CNAME --name undercurrent --data cname.vercel-dns.com
   ```

AI calls can take 20–90 seconds; `vercel.json` raises the function timeout to 300 s.

## Development

```bash
make test     # analytics, API, CSV import, shim and simulation tests (no model calls; a fake LLM plants known effects)
make api      # backend only, auto-reload
make web      # frontend only
make serve    # build the UI and serve everything from FastAPI on :8010
```

API docs: http://localhost:8010/api/docs

```
backend/app/
  analytics.py    polling average, house effects, event impact, analogs
  prompts.py      system prompt, candidate dossier, task prompts
  ai_schemas.py   structured-output schemas for each AI feature
  llm.py          Anthropic SDK client (streaming + structured outputs)
  main.py         FastAPI routes under /api
  storage.py      MongoDB or JSON-file storage
  importers.py    CSV import
  sample_data.py  fictional demo campaign
  sim/            simulations: demographics.py (sampling, raking), personas.py (traits, CSV import),
                  panel.py, candidate.py (calibration, backtest), social.py + network/hawkes/feed/dynamics,
                  survey.py (closed-ended surveys), validation.py (OpinionQA scoring),
                  metrics.py, runner.py (step protocol), routes.py
scripts/                 fetch_opinionqa.py, validate.py, experiments.py, seed_demos.py
docs/                    validation.md
shim/claude_cli_api.py   Claude Code CLI exposed as /v1/messages
frontend/src/            React + Vite UI (charts are hand-built SVG)
api/index.py             Vercel entrypoint
```
