# NFL Player State Engine v0.9

A leakage-safe, probabilistic NFL player-state, fantasy valuation, and live draft-decision system.

The repository has grown from a quantile projection engine into **Fourth Down Lab**, a league-aware decision platform that keeps four things deliberately separate:

1. **Football outcomes** — what a player is likely to do on the field.
2. **League value** — what those outcomes are worth under the exact scoring and roster economy.
3. **Draft-room timing** — when that player is likely to disappear in this platform/format.
4. **External evidence** — expert rankings, markets, injuries, depth charts, practice observations, and news that can challenge the model without becoming truth by default.

> **Research and entertainment only.** The project does not place wagers or promise profit. Predictive and market results should remain timestamped, auditable, and evaluated out of sample.

## What v0.9 adds

### Exact and auditable league scoring

League-specific scoring is now applied **before replacement level and VORP** whenever the projection artifact contains component stat quantiles or already-scored league simulation quantiles.

Scoring priority:

```text
correlated/provided league quantiles
        ↓
complete football component quantiles
        ↓
generic fantasy-point fallback
```

The fallback remains supported for compatibility but is explicitly labeled `generic_points_fallback`. The API and War Room show scoring exactness instead of pretending every projection is custom-scoring exact.

### One authoritative league interpretation

Sleeper, ESPN, waiver, lineup, trade, and draft workflows now share the same `LeagueConfig` translation.

The modern ESPN adapter reads:

- `position_slot_counts`;
- list-based scoring rules;
- `OP`/superflex slots;
- supported passing/rushing/receiving scoring weights;
- unsupported live scoring rules as provenance rather than guessed values.

This prevents one product surface from interpreting a 2QB or custom-scoring league differently from another.

### Dynamic scarcity challenger

The production v0.8 live score remains authoritative, while v0.9 exposes a research challenger built around the actual positional supply curve:

- players remaining above replacement;
- replacement slope;
- next-player VORP drop;
- expected same-position selections before your next turn;
- expected positional supply at your next pick;
- probability-weighted best alternative likely to survive;
- positional value lost by waiting.

The challenger is **not automatically promoted**. Historical replay must show better roster utility.

### Ranking calibration, without consensus mimicry

External rankings and ADP are normalized into a common point-in-time schema and attached as audit context only.

The source registry includes paths for:

- FantasyPros ECR and ADP;
- nflverse ffverse rankings;
- Fantasy Life;
- ESPN;
- RotoWire;
- PFF;
- Rotoworld;
- Sleeper and ESPN draft markets;
- Yahoo;
- NFFC;
- FFPC;
- Underdog.

Preferred ingestion order:

```text
maintained official API
    > maintained public data client
    > supported platform archive
    > licensed export
    > user-provided export
    > explicit permitted public snapshot
```

No brittle scraper is required for the core system.

### Format-robustness benchmark

The same projected player pool can be reranked across adversarial league configurations:

- 8 / 12 / 14 teams;
- 1QB / 2QB / superflex;
- standard / half-PPR / PPR;
- TE premium;
- expanded shallow-league starting lineups.

Validation includes structural monotonicity, Spearman/Kendall agreement, top-K overlap, rank MAE, scoring exactness, and **format-delta agreement**. The latter asks whether players move correctly when only the format changes.

### Evidence fusion instead of news sentiment

Unstructured public reporting is classified as:

```text
OFFICIAL
DIRECT_OBSERVATION
REPORTED
COACH_QUOTE
PLAYER_QUOTE
ANALYSIS
SPECULATION
```

Claims map into football states such as availability, starter security, snap share, route participation, target share, carry share, goal-line role, and third-down role with source-aware decay.

Structured nflverse injuries, depth charts, and snap counts bypass sentiment extraction entirely and become direct role-state evidence.

### Historical policy replay

Ranking challengers can be replayed against the **same frozen historical candidate sets** as production and evaluated on downstream utility and oracle regret.

A ranking does not promote because it correlates with experts. It promotes only if it improves actual decision utility under timestamp-safe replay.

### Research two-turn planner

`POST /v1/leagues/{league_id}/draft/plan` estimates:

```text
draft candidate now
        +
probability-weighted best value likely to survive to next turn
```

It reports expected two-pick value, q10/q50/q90, likely next targets, and failure-to-survive probability.

It is deliberately stamped `promoted: false` until full opponent-conditioned replay proves it improves decisions.

---

# Draft War Room

The operational Draft War Room is the primary frontend surface.

It shows:

- live league and roster selection;
- exact roster/scoring format;
- current and next snake picks;
- automatic room refresh;
- available player board;
- VORP and replacement rank;
- roster need and marginal roster value;
- tier cliffs;
- survival-to-next-pick;
- dynamic positional wait loss;
- scoring exactness/fallback;
- external expert consensus and disagreement;
- 2–5 player comparison;
- research two-turn lookahead;
- freshness and model provenance.

Python remains the numerical authority. React renders and selects returned values. Gemini retrieves, compares, and explains deterministic tool outputs.

## Operational API

```text
GET  /v1/draft/leagues
GET  /v1/leagues/{league_id}/draft/board
POST /v1/leagues/{league_id}/draft/compare
POST /v1/leagues/{league_id}/draft/plan
GET  /v1/rankings/sources
GET  /v1/leagues/{league_id}/rankings/audit
```

Broader Product API surfaces also include player boards, waivers, lineups, trade analysis, league needs, NFL state, research summaries, and Copilot context.

---

# Quick start

Python 3.11+ is supported.

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

python -m pip install -e ".[dev,intelligence,api,espn]"
```

Run the tests:

```bash
ruff check src tests
pytest
```

## Start the Product API

```bash
python -m player_state_engine.api
```

The API listens on port 8000 by default.

## Start Fourth Down Lab

```bash
cd apps/gemini-fantasy-console
npm ci
cp .env.example .env
npm run dev
```

The Express/Vite app listens on port 3000 by default.

For Gemini explanations, keep `GEMINI_API_KEY` server-side. The deterministic fantasy product continues to work without it.

---

# Live fantasy league setup

Copy the example portfolio:

```bash
cp configs/fantasy/leagues.example.yaml configs/fantasy/leagues.yaml
```

Then sync configured leagues:

```bash
python scripts/sync_fantasy_leagues.py \
  --config configs/fantasy/leagues.yaml
```

Sleeper is supported through its public league data. ESPN uses the optional `espn-api` adapter and, for private leagues, server-side environment credentials:

```bash
export PSE_ESPN_S2=...
export PSE_ESPN_SWID=...
```

Credentials are not serialized into league snapshots.

---

# nflverse data

The maintained `nflreadpy` client is the preferred nflverse boundary.

Core data includes:

- player statistics;
- schedules;
- players;
- rosters;
- weekly rosters;
- depth charts.

Optional data includes snap counts, participation, Next Gen Stats aggregates, and FTN charting.

v0.9 can additionally acquire fail-soft intelligence tables:

- injuries;
- fantasy player-ID mappings;
- ffverse rankings;
- fantasy opportunity data.

The Python data function supports:

```python
from player_state_engine.data.nflverse import download_nflverse

download_nflverse(
    [2024, 2025, 2026],
    "data/raw/nflverse",
    include_optional=True,
    include_intelligence=True,
)
```

Optional/intelligence-source outages do not invalidate the core player-state build.

---

# External ranking snapshots

## FantasyPros official API

Configure:

```bash
export PSE_FANTASYPROS_API_KEY=...
```

Archive a point-in-time snapshot:

```bash
python scripts/fetch_fantasypros_rankings.py \
  --season 2026 \
  --position ALL \
  --scoring HALF \
  --teams 12 \
  --qb-format 2qb
```

Do not overwrite historical snapshots. Rank movement is itself information.

## Licensed or user-provided exports

```bash
python scripts/normalize_ranking_export.py \
  --input rankings.csv \
  --source fantasy_life \
  --source-kind expert \
  --ranking-type draft \
  --scoring ppr \
  --teams 8 \
  --qb-format 2qb \
  --output data/external/rankings/fantasy_life/20260818T030000Z.parquet
```

The canonical schema preserves source, source kind, identity match confidence, format metadata, rank range/dispersion, capture time, and source URL.

See [`docs/data/ranking_and_news_sources.md`](docs/data/ranking_and_news_sources.md).

---

# Ranking validation

Run the format matrix:

```bash
python scripts/build_format_ranking_benchmark.py \
  --projections artifacts/predictions/product_player_values.csv \
  --rankings-root data/external/rankings
```

Outputs include per-format boards, positional summaries, external-ranking metrics, structural checks, and a promotion report.

A ranking challenger is not promoted unless required gates pass. Historical roster-utility replay is required by default.

See:

- [`docs/modeling/ranking_calibration_v09.md`](docs/modeling/ranking_calibration_v09.md)
- [`docs/releases/v0.9.md`](docs/releases/v0.9.md)

---

# Projection and simulation engine

The core model remains leakage-safe and probabilistic.

Major capabilities include:

- lag, rolling, and exponentially weighted player states;
- position/team/opponent priors;
- target-aware hybrid quantile models;
- position-specific opportunity heads;
- temporal holdout and walk-forward evaluation;
- multi-season baselines;
- conformal calibration challengers;
- q10/q50/q90 output distributions;
- correlated Monte Carlo simulation;
- future-week slate construction;
- prospect and team-context features;
- guarded intelligence ablations;
- model registry and promotion gates.

Typical flow:

```text
nflverse / frozen external evidence
              │
              ▼
      immutable raw tables
              │
              ▼
      leakage-safe player state
              │
              ▼
       football quantile models
              │
              ▼
 correlated football simulation
              │
              ▼
 exact league scoring transformation
              │
              ▼
 replacement / VORP / scarcity
              │
              ▼
 roster counterfactual + room timing
              │
              ▼
      live draft recommendation
```

## Core training workflow

```bash
pse build-features \
  --stats data/raw/nflverse/player_stats.parquet \
  --schedules data/raw/nflverse/schedules.parquet \
  --output data/processed/weekly_features.parquet

pse train \
  --features data/processed/weekly_features.parquet \
  --output artifacts/models/quantile_bundle.joblib \
  --metrics artifacts/reports/holdout_metrics.csv
```

Create and score a future slate:

```bash
pse make-slate \
  --stats data/raw/nflverse/player_stats.parquet \
  --schedules data/raw/nflverse/schedules.parquet \
  --season 2026 --week 1 \
  --output data/processed/slate_2026_w01.parquet

pse predict \
  --model artifacts/models/quantile_bundle.joblib \
  --slate data/processed/slate_2026_w01.parquet \
  --output artifacts/predictions/2026_w01.parquet
```

---

# Validation philosophy

The project uses a **champion/challenger** discipline.

A clever model, external source, social signal, or draft heuristic does not gain production authority merely because it exists.

Promotion should require evidence such as:

```text
point-in-time integrity       PASS
structural format tests       PASS
calibration                   acceptable
historical utility            improves
oracle regret                 not materially worse
source/identity coverage      understood
CI                            PASS
```

Important negative results are retained. Examples in the repository show that additional opportunity/intelligence features can have high coverage and still fail out-of-sample promotion.

This is a feature, not a failure. The codebase is designed to reject complexity that does not earn its place.

---

# Intelligence and public context

The intelligence subsystem is optional and provenance-first.

Collectors support authorized official APIs, RSS, robots-aware public pages, and explicitly configured sources. Access controls, authentication barriers, CAPTCHAs, and private-network destinations are not bypassed.

Public player-context features remain secondary and must pass timestamped ablations before entering production models.

Social/public persona features describe observable public football-context language. They are not psychological diagnoses.

See:

- [`docs/intelligence.md`](docs/intelligence.md)
- [`docs/intelligence_experiments.md`](docs/intelligence_experiments.md)
- [`docs/data/ranking_and_news_sources.md`](docs/data/ranking_and_news_sources.md)

---

# Google AI Studio / Gemini

Fourth Down Lab is designed to run as a React + Express application with the Python Product API as its numerical source of truth.

For AI Studio work, read:

```text
ai_studio/BUILD_PROMPT.md
ai_studio/DRAFT_WAR_ROOM_PROMPT.md
docs/product/gemini_ai_studio.md
docs/product/draft_war_room_frontend.md
docs/modeling/ranking_calibration_v09.md
```

Gemini may:

- retrieve live draft state;
- compare candidates;
- retrieve ranking calibration;
- explain model-versus-market disagreement;
- surface uncertainty;
- retrieve the research two-turn plan.

Gemini may **not** invent or independently calculate projections, VORP, scarcity, roster marginal value, survival probabilities, or production draft actions.

---

# Repository map

```text
src/player_state_engine/
├── api/                 Product, Draft War Room, ranking-audit and research APIs
├── data/                nflverse ingestion, storage, synthetic fixtures
├── evaluation/          backtests, calibration, ranking replay and promotion gates
├── fantasy/             scoring, valuation, draft, roster simulation, rankings
├── features/            leakage-safe state construction
├── intelligence/        availability, typed news evidence, public context, role state
├── integrations/        Sleeper, ESPN, FantasyPros, source registry
├── learning/            model registry and champion/challenger workflow
├── models/              quantile and baseline models
├── product/             canonical league/product schemas
└── simulation/          correlated fantasy/game simulation

apps/gemini-fantasy-console/
├── src/components/DraftWarRoom.tsx
├── src/lib/draftApi.ts
├── server/gemini.ts
└── shared/draft-types.ts
```

---

# Key documentation

Start with:

- [`project_goals.md`](project_goals.md)
- [`AGENTS.md`](AGENTS.md)
- [`docs/releases/v0.9.md`](docs/releases/v0.9.md)
- [`docs/modeling/ranking_calibration_v09.md`](docs/modeling/ranking_calibration_v09.md)
- [`docs/modeling/draft_survival_training.md`](docs/modeling/draft_survival_training.md)
- [`docs/product/draft_war_room_frontend.md`](docs/product/draft_war_room_frontend.md)
- [`docs/product/gemini_ai_studio.md`](docs/product/gemini_ai_studio.md)
- [`docs/data/ranking_and_news_sources.md`](docs/data/ranking_and_news_sources.md)
- [`docs/validation.md`](docs/validation.md)

Historical benchmark and experiment documentation remains in `docs/` and is intentionally retained for auditability.

---

# Current boundaries

v0.9 intentionally does **not** claim that:

- generic fantasy-point artifacts are custom-scoring exact;
- external expert consensus is ground truth;
- every licensed ranking provider is automatically fetched;
- the dynamic-scarcity challenger has beaten production yet;
- the two-turn planner has earned promotion;
- every opponent's future draft policy is fully modeled;
- public social/persona features improve fantasy forecasts;
- news text can replace official structured injury or role data.

Those are research questions with explicit paths to validation.

## Core principle

A useful football model should know **what it knew, when it knew it, how uncertain it was, and why a new idea earned production authority**.
