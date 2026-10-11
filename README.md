# Undercurrent

Candidate analysis for campaigns. Undercurrent lines up a candidate's polling with what they said and did, measures which actions moved the numbers, forecasts how a new speech or interview will land, and recommends what to do next.

- **Overview**: a house-effect-adjusted polling average with every event plotted on it. Click an event to see the polls in the windows before and after it. Effects are pooled by topic and by format (debates, ads, interviews…).
- **Insights**: Claude reads the measured impacts and the candidate's actual words and explains what is driving the numbers, including language patterns that track with gains or losses.
- **Forecast**: paste a draft speech, interview prep or ad script. Undercurrent finds similar past events, computes a statistical prior from how polls moved after them, and Claude adjusts it line by line. You get an expected effect with a range, segment reactions, risky lines with rewrites, likely headlines and opponent attack lines.
- **Strategy**: priorities, messages to amplify or reframe, which formats to do more of, and a 30-day plan, all tied to the events they rest on.
- **Simulations**: populations of AI agents modeled on specific people. Show them a message, product or policy and see who moves and why (message tests), or watch a news event spread across a simulated social feed and test responses to it (social scenarios). See [Simulations](#simulations).

The deployed version uses **Claude Haiku 5.5** (`claude-haiku-5-5`). For local testing, you can route the same requests to the **Claude Code CLI** through a small FastAPI shim, so no API key is needed.

## Quick start

```bash
make setup
cp .env.example .env     # then add ANTHROPIC_API_KEY, or use the CLI shim below
make dev                 # API on :8010, UI on http://localhost:5173
```

Open the app and click **Explore a demo campaign**: a fictional governor's race with synthetic polls in which known effects were planted at each event, so you can check that the analysis recovers them.

### Testing with the Claude Code CLI instead of an API key

```bash
make dev-cli
```

This starts `shim/claude_cli_api.py` on `:8788` and runs the backend with `LLM_BACKEND=claude-cli`. The shim implements the part of `POST /v1/messages` that Undercurrent uses: system prompt, text messages, structured outputs (`output_config.format` → `claude -p --json-schema`), `effort`, and streaming (it replays the finished result as the same SSE events the API sends). The app keeps using the official Anthropic SDK; only `base_url` changes. Each request runs as a fresh `claude -p` with tools, MCP servers and your customizations turned off (`--tools "" --safe-mode`), from an empty working directory. It uses whatever account `claude` is logged into.

You can run the shim on its own and point any Anthropic SDK client at it:

```bash
make shim
```

```python
client = anthropic.Anthropic(api_key="unused", base_url="http://127.0.0.1:8788")
```

Shim settings: `SHIM_MODEL` (force a model for every request, e.g. `sonnet`), `SHIM_TIMEOUT` (seconds, default 300), `SHIM_MAX_CONCURRENCY` (default 3), `CLAUDE_BIN`. The shim is for testing only: no client tools and no images, and multi-turn histories are flattened into a transcript.

## How the numbers work

All arithmetic lives in [`backend/app/analytics.py`](backend/app/analytics.py) and is deterministic. The model is given these numbers and is not asked to compute them.

- **Poll variance** = sampling error `p(100−p)/n` (n capped at 3,000) + a fixed 1.5-pt non-sampling error.
- **House effects**: each pollster's average residual against a leave-one-out average of *other* pollsters, shrunk toward zero and centered, then subtracted.
- **Polling average**: causal (no look-ahead) inverse-variance average with a 7-day half-life, so the value on a date uses only polls released by then.
- **Event impact**: inverse-variance mean of adjusted polls in the N days after the event minus the N days before (N defaults to 14 and can be changed in the UI), with a standard error and z-score. Signals: strong |z|≥2.58, clear ≥1.96, weak ≥1.28. Events whose windows overlap are flagged because credit is ambiguous. The same is computed per segment (crosstabs).
- **Topic / format effects**: inverse-variance pooling of event impacts.
- **Forecast prior**: similarity-weighted (topic overlap and format) pooling of the most similar past events, shrunk toward zero, with an 80% predictive range. Claude starts from this prior and must justify any move away from it.

These are correlations between events and polls, not causal estimates. A typical 2-week polling swing is shown on the dashboard so you can see how big an effect has to be before it is distinguishable from noise.

## Simulations

Open **Simulations** in the top bar, or the **Simulate** tab on a candidate. The engine is general: any stimulus (an ad, a speech, a product pitch, a policy) and any questions. Candidate hooks add calibration and backtests.

The design follows two papers:

- **Park et al. (2024), *Generative Agent Simulations of 1,000 People*** (Stanford HAI). Each agent is the model given one person's life-history interview plus notes written from four expert perspectives (psychologist, behavioral economist, political scientist, demographer). Agents built from real two-hour interviews reproduced people's General Social Survey answers 85% as well as the people reproduced their own answers two weeks later; agents built from survey answers alone reached 82%, and demographics alone 74%.
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

Runs advance in steps driven by the open browser tab (`POST /api/sim/runs/{id}/step`): each step claims a lease, makes calls in parallel until its time budget is spent, and saves results under fixed ids, so it works on a 300-second serverless function and a second tab just watches. Estimates are shown before you start. On Haiku 5.5, generating 200 interview personas and running a three-arm panel on them costs roughly $0.50–1 in total; time is the real limit, especially through the CLI shim (about 3 calls at once, 15–40 s each). On Vercel, simulations require `MONGODB_URI`.

Treat results as a way to compare messages and find risks, not as a poll: intervals measure simulation noise only, and LLM agents can stereotype groups and overreact to messages.

## Data

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
| `SIM_MODEL` | `LLM_MODEL` | model for simulation agents |
| `SIM_CONCURRENCY` | `12` (`3` with the shim) | parallel calls per step |
| `SIM_STEP_SECONDS` | `45` (`150` on Vercel) | time budget per step |
| `SIM_MAX_CALLS_PER_RUN` | `5000` | hard cap per run |
| `SIM_MAX_AGENTS` / `SIM_MAX_SOCIAL_AGENTS` | `500` / `200` | |

## Deploying to undercurrent.deveshkumar.net

The repo is set up for Vercel: the Vite build is served statically and `api/index.py` runs the FastAPI app as a Python function (`vercel.json` rewrites `/api/*` to it).

1. **Database**: Vercel's filesystem is ephemeral, so use MongoDB Atlas (a free M0 cluster is plenty). Create a cluster and a database user, allow access from anywhere (`0.0.0.0/0`, since Vercel IPs vary), and copy the `mongodb+srv://…` connection string.
2. **Project and secrets**:
   ```bash
   vercel link
   vercel env add ANTHROPIC_API_KEY production
   vercel env add MONGODB_URI production
   vercel env add ACCESS_CODE production     # strongly recommended: the app spends your API credits
   vercel --prod
   ```
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
                  metrics.py, runner.py (step protocol), routes.py
shim/claude_cli_api.py   Claude Code CLI exposed as /v1/messages
frontend/src/            React + Vite UI (charts are hand-built SVG)
api/index.py             Vercel entrypoint
```
