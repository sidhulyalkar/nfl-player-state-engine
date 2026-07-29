# NFL Player State Engine v0.5

A leakage-safe, probabilistic NFL projection system for weekly player states, fantasy outcomes, paper-market evaluation, and correlated Monte Carlo simulation.

The engine is deliberately built as a sturdy first possession rather than a decorative Hail Mary. It starts with strong tabular baselines, explicit uncertainty, immutable prediction artifacts, and temporal validation. Tracking models, text/news encoders, play-sequence models, and learned correlations can be added only after the baseline earns them.

> **Research and entertainment only.** This repository does not place wagers, connect to sportsbooks, or promise profit. Laws vary by location. Keep monetary evaluation paper-only until the model has accumulated substantial timestamped out-of-sample evidence.

## What is included

- Maintained Python ingestion through [`nflreadpy`](https://github.com/nflverse/nflreadpy)
- Weekly player statistics and schedule context
- CSV and Parquet storage plus optional DuckDB views
- Synthetic miniature NFL league for offline development
- Leakage-safe lag, rolling, exponentially weighted, position-prior, team, and opponent features
- Target-aware hybrid quantile models, including position-specific carries heads
- Temporal holdout evaluation and walk-forward backtesting
- Multi-season benchmark against rolling-stat and position-prior quantile baselines
- Position-specific quantile and interval calibration reports
- Earlier-season target-and-position conformal calibration embedded in guarded challengers
- Explicit active → participation → volume → conversion → fantasy opportunity heads
- Future-week slate construction from historical player states
- Correlated Monte Carlo simulation for fantasy distributions
- Manual prop-board scoring and a paper-only settlement ledger
- Disabled-by-default official availability, structured news, and public player-context feature families
- Capped residual/uncertainty modifier for soft intelligence evidence
- Required intelligence ablations, shuffled-player control, and shifted-time leakage control
- Official API connectors for X, Threads, Instagram Business Discovery, and approved TikTok Research access
- Robots-aware static and JavaScript-rendered public-page collectors with SSRF guards and evidence provenance
- Guarded continual batch learning, candidate registry, promotion gates, and weekly refresh scaffold
- Historical snap, participation, depth-chart, injury, combine, draft and roster acquisition with checksum manifests
- Frozen 23,003-player-week opportunity ablation and leakage positive control
- Combine, draft-capital and optional college-production rookie priors
- Observable coaching/team play-structure fingerprints and player-system fit
- High-chance opportunity, breakout and reason-code watchlists
- League-specific scoring, replacement levels and decision boards for drafts, lineups, waivers, trades, stashes and dynasty
- Streamlit projection explorer
- CLI, tests, Dockerfile, CI workflow, and extension roadmap

## Architecture

```text
nflverse / synthetic fixtures
            │
            ▼
 immutable raw tables ───────► DuckDB catalog
            │
            ▼
 canonical weekly player-game rows
            │
            ▼
 leakage-safe state construction
 lag + rolling + EWM + position/team/opponent priors
            │
       ┌────┴───────────┐
       ▼                ▼
 temporal backtest   future-week slate
       │                │
       ▼                ▼
 quantile models ───► conformal q10 / q50 / q90 predictions
                           │
                  ┌────────┴─────────┐
                  ▼                  ▼
          correlated simulation   paper prop scoring
                  │                  │
                  ▼                  ▼
       player/team/game ranges   timestamped ledger
```

## v0.5 research and fantasy commands

```bash
# Re-evaluate the frozen real benchmark with earlier-season calibration
python scripts/run_conformal_benchmark.py

# Train explicit opportunity heads on a feature table
pse train-opportunity-heads --features data/processed/weekly_features.parquet

# Normalize official evidence and extract structured news claims
pse build-official-availability --evidence examples/official_availability_evidence_template.csv
pse extract-news-claims --documents data/external/intelligence/documents.jsonl

# Run all required intelligence ablations and controls
pse benchmark-intelligence-ablations \
  --features data/processed/weekly_features_with_all_intelligence.parquet \
  --target fantasy_points_ppr
```

See `docs/calibration_real_2021_2025.md`, `docs/opportunity_engine.md`, and `docs/intelligence_experiments.md`.

### v0.5 experiment and decision layer

```bash
# Completed frozen proxy ablation
python scripts/run_frozen_opportunity_ablation.py

# Download actual historical opportunity and availability sources locally
python scripts/acquire_historical_sources.py --seasons 2020 2021 2022 2023 2024 2025
python scripts/run_historical_source_ablation.py

# Build prospect, team-context and fantasy decision artifacts
pse build-prospect-features --combine combine.csv --draft draft.csv --college college.csv
pse build-team-context --pbp play_by_play.parquet
pse rank-opportunities --features weekly_features.parquet
pse fantasy-decision-board --projections projections.csv --decision draft
```

The completed proxy experiment found that repackaged lagged box-score opportunity features did not improve the frozen champion. Mean pinball worsened 3.14%, while a deliberately leaked future-shift control improved 27.04%. This negative result directs the next test toward genuinely new snaps, participation, depth-chart and official-availability information. See `docs/experiment_opportunity_availability_v05.md` and `docs/fantasy_decision_framework.md`.

The subsequent actual-source experiment also rejected promotion: the best
eligible combination worsened mean pinball by 1.508% across 23,003 held-out
2022–2025 player-weeks and reduced q10–q90 coverage from 0.821 to 0.717.
High snap, participation and depth-chart coverage makes this a meaningful
negative result rather than an inner-join artifact. Compact metrics and coverage
are available through `/v1/research/summary` and the frontend Model Lab; see
`docs/historical_source_acquisition.md`.

## Fastest start: synthetic smoke test

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux
# source .venv/bin/activate

python -m pip install -e ".[dev,dashboard,intelligence]"
pse smoke-test --work-dir .smoke
```

The smoke test creates:

```text
.smoke/data/raw/player_stats.csv
.smoke/data/processed/weekly_features.csv
.smoke/artifacts/models/quantile_bundle.joblib
.smoke/artifacts/predictions/predictions_2024_w13.csv
.smoke/artifacts/reports/holdout_metrics.csv
.smoke/artifacts/reports/*_simulation.csv
```

The synthetic league has persistent player and team skill, schedule effects, opponent effects, injuries/absences, and random game variation. It validates the software pipeline, not NFL predictive quality.

## Live-data workflow

### 1. Download public data

```bash
pse download \
  --season 2021 --season 2022 --season 2023 --season 2024 --season 2025 \
  --output-dir data/raw/nflverse
```

Core tables:

- `player_stats`
- `schedules`
- `rosters`
- `rosters_weekly`
- `depth_charts`

Optional tables can be attempted with `--include-optional`:

```bash
pse download --season 2024 --season 2025 \
  --output-dir data/raw/nflverse --include-optional
```

Optional sources include snap counts, participation, Next Gen Stats aggregates, and FTN charting. They may have different update schedules or incomplete coverage, so failures do not block the core pipeline.

### 2. Build features

```bash
pse build-features \
  --stats data/raw/nflverse/player_stats.parquet \
  --schedules data/raw/nflverse/schedules.parquet \
  --output data/processed/weekly_features.parquet
```

### 3. Train quantile models

```bash
pse train \
  --features data/processed/weekly_features.parquet \
  --output artifacts/models/quantile_bundle.joblib \
  --metrics artifacts/reports/holdout_metrics.csv
```

The default targets are:

- PPR fantasy points
- Targets
- Carries
- Receptions
- Receiving yards
- Rushing yards
- Passing yards

Each target receives q10, q50, and q90 models. The production `HybridQuantileModelBundle` uses pooled heads for most targets and independent position heads for carries, where the real benchmark showed pooled zero inflation collapsing QB/RB medians. Predictions are corrected if independently fitted quantiles cross.

### 4. Create a future-week slate

The schedules file must include the target week.

```bash
pse make-slate \
  --stats data/raw/nflverse/player_stats.parquet \
  --schedules data/raw/nflverse/schedules.parquet \
  --season 2026 --week 1 \
  --output data/processed/slate_2026_w01.parquet
```

The initial slate builder infers active players from recent appearances. Before serious deployment, replace or augment this with timestamped rosters, depth charts, official game status, and projected participation.

### 5. Predict

```bash
pse predict \
  --model artifacts/models/quantile_bundle.joblib \
  --slate data/processed/slate_2026_w01.parquet \
  --output artifacts/predictions/2026_w01.parquet
```

### 6. Simulate the slate

```bash
pse simulate \
  --predictions artifacts/predictions/2026_w01.parquet \
  --target fantasy_points_ppr \
  --output-dir artifacts/reports/2026_w01
```

The initial simulator uses a Gaussian copula and heuristic within-game correlations. QB-receiver pairs receive stronger positive dependence, while players competing for the same backfield receive less. These correlations are transparent placeholders for a future learned residual-correlation model.

## Paper-only prop evaluation

Create a timestamped CSV matching `examples/props_template.csv`:

```csv
player_id,target,line,over_odds,under_odds,captured_at_utc,source
00-0031234,passing_yards,249.5,-110,-110,2026-09-10T16:00:00Z,manual
```

Score it without placing a bet:

```bash
pse score-props \
  --predictions artifacts/predictions/2026_w01.parquet \
  --props examples/props_template.csv \
  --output artifacts/reports/scored_props.csv
```

After games finish, create outcomes matching `examples/outcomes_template.csv`, then settle the paper ledger:

```bash
pse settle-props \
  --scored artifacts/reports/scored_props.csv \
  --outcomes examples/outcomes_template.csv \
  --output artifacts/reports/settled_props.csv
```

The scorer reports model probability, no-vig market probability, probability edge, and expected profit per $1 under the supplied odds. These estimates are only as trustworthy as the calibration, timestamp discipline, market snapshot, and distributional assumptions behind them.

## Completed real benchmark

The repository includes a full 2020–2025 nflverse benchmark under `artifacts/reports/benchmark_real/`. The 2020 season is the warm-up and 2021–2025 are expanding-window out-of-sample seasons.

The original pooled quantile engine beat the strongest baseline on six of seven targets by mean pinball loss. Carries failed because zero-heavy WR rows collapsed QB/RB medians. A position-specific carries diagnostic reduced mean pinball from 0.7844 to 0.5091, narrowly beating rolling-5 at 0.5157, and v0.4 promotes that architecture into production training.

Reproduce the exact run and source-hash manifest with:

```bash
python scripts/run_real_benchmark.py
```

See [`docs/benchmark_real_2020_2025.md`](docs/benchmark_real_2020_2025.md).

## Multi-season baseline benchmark

Run the same walk-forward folds through the quantile engine, a five-game rolling baseline, and a historical position-prior baseline:

```bash
pse benchmark-multiseason \
  --features data/processed/weekly_features.parquet \
  --target fantasy_points_ppr \
  --output-dir artifacts/reports/benchmark/fantasy_points_ppr
```

The output includes overall metrics, position-specific metrics, fold metrics, empirical quantile calibration, q10-q90 interval calibration, archived predictions, and a Markdown report. See [`docs/benchmarking.md`](docs/benchmarking.md).

## Injury, news, and public-context scaffolds

The intelligence layer is optional and disabled by default. It can collect authorized public content through official APIs, RSS, static public pages, or JavaScript-rendered pages that are genuinely available to a clean unauthenticated browser. The collectors honor robots.txt, block private-network destinations, and stop on login, CAPTCHA, or challenge pages. They do not reuse sessions or bypass access controls.

```bash
python -m pip install -e ".[intelligence]"
# Optional rendered public pages
python -m pip install -e ".[browser]"
playwright install chromium

pse collect-intelligence \
  --registry examples/player_sources_template.csv \
  --output data/external/intelligence/documents.jsonl

pse build-personas \
  --documents data/external/intelligence/documents.jsonl \
  --output data/processed/persona_features.parquet \
  --evidence artifacts/reports/persona_evidence.json
```

Persona outputs describe observable public football-context language, not psychological diagnoses. They remain excluded from the main model until a frozen benchmark and point-in-time ablation show incremental value. See [`docs/intelligence.md`](docs/intelligence.md).

## Continual batch learning

v0.4 can refresh completed weeks and train gated challengers without silently replacing the champion:

```bash
python scripts/weekly_refresh.py --config configs/base.yaml
pse learning-status --registry artifacts/models/registry.json
```

Automatic promotion is disabled. After reviewing the candidate benchmark and calibration artifacts:

```bash
pse promote-model MODEL_ID --registry artifacts/models/registry.json
```

The included GitHub Actions workflow provides a weekly scaffold. See [`docs/continual_learning.md`](docs/continual_learning.md).

## Walk-forward backtest

```bash
pse backtest \
  --features data/processed/weekly_features.parquet \
  --target fantasy_points_ppr \
  --min-train-weeks 24 \
  --retrain-every 4 \
  --output-dir artifacts/reports/backtest
```

Every test week is predicted using earlier weeks only. Do not replace this with a random row split. Random splitting allows neighboring weeks, recurring players, and season context to leak across the boundary.

## Dashboard

```bash
pse dashboard --predictions artifacts/predictions/2026_w01.parquet
```

The dashboard displays player q10/q50/q90 ranges and supports team and position filtering.

## Player-state definition

In v0.1, a player state is an interpretable vector assembled before kickoff:

- Recent opportunity and production lags
- Rolling means and variability over 3, 5, and 8 games
- Exponentially weighted states with 2, 4, and 8-game half-lives
- Position-level priors
- Team offensive volume
- Opponent production allowed
- Home/away, spread, total, rest, roof, surface, temperature, wind, and season timing

Export the latest state per player:

```bash
pse export-states \
  --features data/processed/weekly_features.parquet \
  --output artifacts/reports/player_states.csv
```

The longer-term goal is to replace parts of this manually constructed state with a learned latent state while retaining these features as baselines and interpretability anchors.

## Modeling choices

### Why quantiles first?

A median projection cannot distinguish a reliable 12-point player from a volatile player whose mean is also 12. Quantile regression gives a useful distributional skeleton without requiring an unjustified parametric likelihood.

### Why separate targets by eligible position?

Training passing yards on thousands of WR and RB zeros creates an impressive-looking but useless zero predictor. Each target is trained only on plausible positions, then set to zero for ineligible positions at prediction time.

### Why not begin with an LLM or giant transformer?

Weekly NFL samples are limited. Tabular models can expose whether the feature and evaluation machinery contains signal before capacity is multiplied. Future sequence and language models should enter as measurable upgrades, not ceremonial complexity.

## Repository layout

```text
src/player_state_engine/
├── cli.py
├── config.py
├── state.py
├── data/
│   ├── nflverse.py
│   ├── synthetic.py
│   ├── io.py
│   └── catalog.py
├── features/
│   └── weekly.py
├── models/
│   ├── quantile.py
│   ├── position_quantile.py
│   ├── hybrid.py
│   └── baselines.py
├── learning/
│   ├── registry.py
│   ├── gates.py
│   └── workflow.py
├── intelligence/
│   ├── availability.py
│   ├── persona.py
│   └── collectors/
├── evaluation/
│   ├── metrics.py
│   ├── backtest.py
│   └── market.py
├── simulation/
│   ├── distributions.py
│   └── game.py
├── pipelines/
│   └── workflows.py
└── dashboard/
    └── app.py
```

## Data provenance and licenses

The engine uses nflverse through its maintained Python client. nflverse data tables have their own provenance and licenses. Preserve source attribution and review each optional dataset before redistribution. FTN charting data, for example, has explicit attribution requirements.

Raw datasets and generated model artifacts are excluded from Git by default.

## Known limitations in v0.4

- Live injury/news feeds require authorized source configuration
- No true snap or route projection model yet
- No roster transaction reconciliation
- No learned game-script simulator
- No historical consensus fantasy baseline ingestion
- No automated odds collection
- No closing-line tracking service
- Correlations are heuristic rather than learned
- Quantile density is approximated by a split normal during simulation
- Scheduled continual learning is a scaffold; durable production state should use object storage and a transactional registry
- Public webpage structures and platform permissions can change
- Synthetic tests prove software behavior, while the bundled real benchmark establishes only historical out-of-sample validity

These omissions are intentional boundary markers. The next version should improve one measured weakness at a time.

## Recommended development order

1. Add target-and-position conformal calibration.
2. Add snap, route, target-share, carry-share, and team-volume submodels.
3. Activate official availability and depth-chart evidence in opportunity heads.
4. Add consensus fantasy projections as a timestamped benchmark, never an untracked feature.
5. Learn residual correlations by game, team, and role.
6. Add structured licensed-news role evidence.
7. Test public-context features with shuffled-player and shifted-time controls.
8. Explore play-sequence transformers and tracking-data graph models.

See [`project_goals.md`](project_goals.md), [`AGENTS.md`](AGENTS.md), and [`docs/roadmap.md`](docs/roadmap.md) for the experiment gates and [`docs/validation.md`](docs/validation.md) for the current test status.

## Development

```bash
python -m pip install -e ".[dev,dashboard,intelligence]"
pytest
ruff check src tests
```

Create a local DuckDB catalog:

```bash
pse catalog \
  --database data/player_state_engine.duckdb \
  --table player_stats=data/raw/nflverse/player_stats.parquet \
  --table schedules=data/raw/nflverse/schedules.parquet \
  --table features=data/processed/weekly_features.parquet
```

## Core principle

A useful football model should know what it knew, when it knew it, and how uncertain it was. Everything else is scoreboard confetti.

## v0.6 product layer: Fourth Down Lab

v0.6 adds a league-aware product architecture around the research engine:

- canonical multi-platform `LeagueSnapshot`;
- working Sleeper and CSV imports;
- ownership, free-agent and league power views;
- two-sided trade analysis and suggested trades;
- ranked lineup, waiver and roster-needs Product API endpoints;
- provenance-gated NFL standings plus leakage-safe team-context endpoints;
- frozen research summary and historical player-ranking replay endpoints;
- React 19 + Express 5 Gemini application on Node.js 22;
- Google AI Studio Build prompt and product documentation.

### Run the Product API

```bash
python -m pip install -e ".[api]"
python -m player_state_engine.api
```

### Run the Gemini frontend

```bash
npm install
cp apps/gemini-fantasy-console/.env.example apps/gemini-fantasy-console/.env
npm run dev
```

The npm workspace starts the Express and Vite application on
`http://localhost:3000`. The frontend enters clearly labeled synthetic demo
mode until a league and provenance-bearing player-value artifact are available.
The standings endpoint also fails closed until `PSE_SCHEDULES_DATA_MODE` is
explicitly set to `LIVE_OFFICIAL`, `HISTORICAL_BACKTEST`, or
`SYNTHETIC_DEMO`; the bundled miniature schedule must never be labeled live.
Use `npm run build` for a production build and `npm start` after building.
See:

```text
docs/product/current_package_state.md
docs/product/product_vision.md
docs/product/testing_predictive_capability.md
docs/product/frontend_architecture.md
docs/product/gemini_ai_studio.md
ai_studio/BUILD_PROMPT.md
```

Seed a fully local product demo before starting the API:

```bash
pse seed-product-demo
pse serve-product-api
```
