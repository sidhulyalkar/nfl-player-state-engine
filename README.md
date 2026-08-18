# NFL Player State Engine v0.11

**Fourth Down Lab** is a leakage-safe, probabilistic NFL player-state and fantasy decision system. The project now combines a direct player projection engine with a guarded generative game simulator, then forces both through frozen historical replay before new complexity can affect production decisions.

> Research and entertainment only. The project does not place wagers or promise profit. Predictive, fantasy, and market results should remain timestamped, auditable, and evaluated out of sample.

## The core architecture

```text
                         EVIDENCE
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
     PLAYER             TEAM              COACH / ROLE
      STATE              STATE                STATE
        │                  │                  │
        └──────────────┬───┴──────────────────┘
                       ▼
                GAME ENVIRONMENT
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
  DIRECT PLAYER MODEL       GENERATIVE GAME MODEL
          │                         │
     q10/q50/q90              play-by-play draws
          │                         │
          └────────────┬────────────┘
                       ▼
              FROZEN REPLAY LAB
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      CALIBRATION   OPPORTUNITY   BLEND TESTS
          │            │            │
          └────────────┴────────────┘
                       ▼
                 PROMOTION GATE
                       │
                       ▼
              LEAGUE-SPECIFIC VALUE
                       │
                       ▼
             FANTASY DECISION LAYER
```

The repository deliberately separates four questions:

1. **Football outcomes**: what is likely to happen on the field?
2. **League value**: what are those outcomes worth under the exact scoring and roster economy?
3. **Acquisition timing**: when is a player likely to disappear in a draft or waiver market?
4. **External evidence**: what can rankings, injuries, depth charts, coaching changes, practice observations, and markets tell us without becoming truth by default?

## What v0.11 adds

### 1. Expanding weekly frozen replay

The canonical game benchmark now retrains at every historical week boundary:

```text
Week N model = every permitted observation strictly before Week N
```

A Week 8 replay may learn from Weeks 1-7. It may never learn from Week 8 itself.

This is the evaluation protocol the live continual-learning system is supposed to emulate.

Run it with:

```bash
python scripts/run_v011_game_benchmark.py \
  --pbp data/raw/game_intelligence/v011/play_by_play.parquet \
  --schedules data/raw/game_intelligence/v011/schedules.parquet \
  --players data/raw/game_intelligence/v011/players.parquet \
  --player-actuals data/raw/game_intelligence/v011/player_stats.parquet \
  --test-season 2023 \
  --test-season 2024 \
  --test-season 2025
```

Or use the manual workflow:

```text
.github/workflows/v011_historical_game_benchmark.yml
```

### 2. State-conditioned opportunity challenger

The new `StateConditionedOpportunityModel` asks a narrow question before it is allowed into Monte Carlo:

> Given the team and play state, who is most likely to receive this carry or target?

It starts from recency-weighted player share and adds shrunk situational evidence for:

- red zone;
- third down;
- early downs;
- late game;
- leading / neutral / trailing score state;
- distance bucket;
- field zone.

Sparse context is regularized back toward the base role rather than being treated as a new truth.

The first benchmark is deliberately **oracle-state**: realized team play states are held fixed so allocation can be evaluated independently from team-volume and run/pass errors. An oracle-state win does not authorize production usage.

### 3. Direct vs generative quantile blend laboratory

Archived direct-model and game-simulator predictions can now be tested for complementary signal.

```text
Q_blend = w * Q_direct + (1 - w) * Q_generative
```

`QuantileBlendCalibrator` learns `w` only from earlier archived predictions. It can learn position-specific weights when there is enough data and otherwise falls back to a global weight.

The benchmark reports whether the blend beats:

- the direct model;
- the generative model;
- the better of the two components on each weekly fold.

No blend is promoted automatically.

### 4. Stronger research promotion gate

v0.11 requires robustness across time, not one attractive aggregate score.

Default evidence includes:

- multiple held-out seasons;
- hundreds of replayed games;
- play-call calibration;
- team plays, pass rate, and scoring;
- player carries/targets;
- state-conditioned allocation likelihood;
- fantasy quantile pinball loss;
- q10-q90 interval coverage;
- weekly fold win rates;
- manual champion review.

Missing downstream evidence is a failed gate.

## v0.10 game intelligence foundation

v0.10 introduced the point-in-time generative football engine that v0.11 now evaluates more rigorously.

It includes:

- normalized nflverse play-by-play state;
- leakage-safe offense and defense tendency snapshots;
- neutral, early-down, red-zone, third-down, shotgun/no-huddle, pace, EPA, and explosive-play context;
- recency-weighted player carry, target, dropback, and red-zone usage;
- verified coaching/play-caller registry contracts;
- heavily shrunk direct play-caller matchup priors;
- regularized run/dropback probability challenger;
- hierarchical empirical play outcomes;
- score, clock, possession, down, distance, and field-position simulation;
- correlated raw player stat draws;
- exact league rescoring;
- weekly research refresh and immutable evidence registry.

The simulator remains research-only until frozen replay earns a promotion.

## v0.9 league and ranking foundation

The fantasy layer applies league scoring before replacement level and VORP whenever sufficient stat components are available.

Scoring provenance distinguishes:

```text
correlated/provided league draws
        ↓
complete component rescoring
        ↓
generic fantasy-point fallback
```

Sleeper and ESPN league interpretation share one `LeagueConfig`, including multi-QB and superflex slot handling.

External rankings and ADP are normalized into a common timestamped schema and used as challenger/audit context rather than football truth. Supported source paths include FantasyPros, nflverse ff rankings, platform archives, licensed exports, and user-provided exports.

## Research API

The operational API exposes guarded research surfaces:

```text
GET  /v1/research/game-intelligence/sources
GET  /v1/research/game-intelligence/status
GET  /v1/research/game-intelligence/benchmark
POST /v1/research/game-intelligence/simulate
```

Every research response preserves the boundary:

```text
research_only = true
production_projection_changed = false
automatic_promotion = false
```

## Why the project decomposes errors

A fantasy miss can come from several different mechanisms:

```text
wrong team play volume
    ↓
wrong run/pass probability
    ↓
wrong player opportunity allocation
    ↓
wrong completion / rushing / touchdown efficiency
    ↓
wrong fantasy uncertainty
```

v0.11 is designed to tell these apart.

If team play volume is already good, adding a larger pace model is unlikely to be the best use of effort. If target allocation is the failure, route/formation evidence has a clearer hypothesis. If all football layers are good but q10-q90 coverage is poor, uncertainty modeling is the actual problem.

## Evidence roadmap

Interesting future evidence families include:

- offensive-line starter continuity and pressure responsibility;
- defensive front / coverage-response proxies;
- formation and personnel transitions;
- motion, play action, RPO, and screens;
- route participation and alignment;
- third-down, two-minute, and goal-line packages;
- drive-opening scripts and halftime adaptation;
- persistent drive-level strategy state;
- weather trajectory, roof, surface, rest, and travel;
- official crews and penalty environment;
- market disagreement as an external diagnostic sensor.

These are **experiment families**, not trusted model inputs. Every one needs timestamp provenance, an isolated frozen ablation, and a negative control.

## Installation

```bash
python -m pip install -e '.[dev,intelligence,api]'
```

Run tests:

```bash
pytest
```

Lint the package and research scripts:

```bash
ruff check src tests \
  scripts/acquire_game_intelligence_sources.py \
  scripts/build_game_intelligence.py \
  scripts/run_play_call_benchmark.py \
  scripts/run_game_simulation_replay.py \
  scripts/weekly_game_intelligence_refresh.py \
  scripts/run_v011_game_benchmark.py \
  scripts/run_v011_blend_benchmark.py
```

Run the operational API:

```bash
uvicorn player_state_engine.api.operational:app --reload
```

## Repository map

```text
src/player_state_engine/
  game_intelligence/
    benchmark.py       expanding frozen replay + v0.11 gate
    blend.py           direct/generative quantile calibration
    opportunity.py     state-conditioned carry/target challenger
    replay.py          frozen game replay primitives
    simulator.py       research play-by-play state machine
    tendencies.py      team and matchup priors
    usage.py           point-in-time player usage state
  fantasy/             league scoring, valuation, draft/roster tools
  intelligence/        news and structured football evidence
  integrations/        Sleeper, ESPN, rankings, source adapters
  api/                 operational and guarded research surfaces
scripts/
  run_v011_game_benchmark.py
  run_v011_blend_benchmark.py
  weekly_game_intelligence_refresh.py
.github/workflows/
  weekly_game_intelligence.yml
  v011_historical_game_benchmark.yml
```

## Modeling rules

1. No random row splits for weekly NFL evaluation.
2. No feature may use information published after the prediction cutoff.
3. No same-game outcome may enter its own feature vector.
4. Retrospective data is not live data merely because it is downloadable.
5. External consensus is a challenger or sensor, not ground truth.
6. Every complex model must beat a simpler baseline on frozen evidence.
7. Calibration and interval coverage matter alongside point accuracy.
8. No automatic production promotion from a scheduled workflow.
9. No automatic real-money wagering.
10. When an experiment loses, keep the result and change the hypothesis rather than the scoreboard.

See `docs/modeling/game_intelligence_v011.md` and `docs/releases/v0.11.md` for the current research contract.
