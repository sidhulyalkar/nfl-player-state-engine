# NFL Player State Engine v0.13

**Fourth Down Lab** is a leakage-safe, probabilistic NFL player-state and fantasy decision system. It combines direct player projections, league-specific valuation, a guarded generative football simulator, and frozen historical replay so new model complexity has to earn authority before it can affect production decisions.

> Research and entertainment only. The project does not place wagers or promise profit. Predictive, fantasy, and market results should remain timestamped, auditable, and evaluated out of sample.

## Architecture

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
             ┌─────────┴─────────┐
             ▼                   ▼
      DIRECT PLAYER       GENERATIVE GAME
          MODEL                MODEL
        q10/50/90         play-by-play draws
             │                   │
             └─────────┬─────────┘
                       ▼
                FROZEN REPLAY LAB
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
   CALIBRATION      FACTORIAL       NEGATIVE
                     ATTRIBUTION       CONTROLS
       │               │                │
       └───────────────┴────────────────┘
                       ▼
                 PROMOTION GATES
                       │
                       ▼
              LEAGUE-SPECIFIC VALUE
                       │
                       ▼
             FANTASY DECISION LAYER
```

The repository deliberately separates four questions:

1. **Football outcomes:** what is likely to happen on the field?
2. **League value:** what are those outcomes worth under exact scoring and roster economics?
3. **Acquisition timing:** when is a player likely to disappear in a draft or waiver market?
4. **External evidence:** what can rankings, injuries, depth charts, coaching changes, practice information, and markets tell us without becoming truth by default?

## What v0.13 adds

### 1. Drive Volume & State Laboratory

v0.12 made play-calling and player-allocation errors independently measurable. v0.13 attacks the next structural ambiguity: **team play volume**.

The established simulator previously mixed clock runoff into the same empirical sample that supplied yards, first downs, turnovers, and touchdowns, while possessions reset to fixed field positions. v0.13 extracts those mechanisms into an isolated challenger:

```text
DRIVE VOLUME MODEL
    │
    ├── state-conditioned clock runoff
    │     ├── score state
    │     ├── late game
    │     ├── rush / dropback
    │     └── red zone
    │
    └── point-in-time drive-start field position
          ├── offense history
          ├── opponent history
          └── league prior
```

`DriveVolumeModel` is hierarchical, recency weighted, and shrinks sparse contexts toward the team's recent base pace.

### 2. Mechanism-isolated simulation probe

`simulate_matchup_volume_probe` is a parallel research simulator. It does **not** replace the established v0.12 `simulate_matchup` path.

The probe uses independent deterministic RNG streams for:

```text
special teams / fourth down
play calling
play outcomes
player allocation
drive tempo
```

That prevents one challenger from appearing different merely because it consumed an extra random number and shifted every later simulation draw.

Every team draw now exposes:

- drives;
- plays per drive;
- seconds per play;
- mean offensive starting `yardline_100`;
- plays;
- pass rate;
- points.

### 3. Eight-cell expanding replay

v0.13 crosses three model switches:

| Dimension | Baseline | Challenger |
|---|---|---|
| Play calling | profile | learned model |
| Player allocation | static usage | state-conditioned |
| Drive volume | legacy mechanics | learned drive model |

This produces eight replay cells. The primary drive comparison is:

```text
learned_state_drive
        vs
learned_state_legacy
```

Both use learned play calling and state-conditioned player allocation. Only the drive-volume mechanics change.

### 4. Drive-level diagnostics

Historical replay now measures:

```text
team plays MAE
drive-count MAE
plays-per-drive MAE
seconds-per-play MAE
starting-field-position MAE
team points MAE
player opportunity MAE
fantasy pinball / coverage
```

A volume improvement therefore cannot hide a deterioration in scoring, player roles, or fantasy distributions.

### 5. Pace negative control

The isolated pace experiment shuffles `seconds_between_plays` **within team-season**. This preserves each team's marginal pace distribution while destroying the state-to-pace relationship.

For situational pace to earn authority:

```text
real state-conditioned pace
    < team-only pace error
AND
real state-conditioned pace
    < permuted-state pace error
```

If it cannot beat that control, the feature family should be rejected or redesigned rather than expanded.

### 6. Fail-closed research gate

`v013_drive_volume_promotion_gate` requires, by default:

- at least three held-out seasons;
- at least 200 replayed games;
- measurable team-play MAE improvement;
- improved pace accuracy;
- no material regression in drives, plays/drive, starting field position, points, player opportunity, or fantasy pinball loss;
- majority weekly volume wins;
- real pace context beating both team-only and permuted controls.

Even a cleared gate authorizes only manual review for the **research simulator champion**.

```text
research simulator promotion
            ≠
production projection promotion
```

### 7. Evidence-routed v0.14

The v0.13 report routes the next experiment from observed bottlenecks:

```text
volume + fantasy improve
    -> persistent drive strategy state

pace signal real, full volume still weak
    -> possession / drive-transition model

volume improves, fantasy does not
    -> decomposed play outcomes

starting field position is the main win
    -> special-teams / field-position transitions

pace loses to shuffled control
    -> reject / redesign drive context

wins only in stable regimes
    -> evidence-maturity segmentation
```

A transformer or sequence model is deliberately deferred until transparent state models leave stable sequential residuals.

## Run v0.13

Historical runner:

```bash
python scripts/run_v013_drive_volume_benchmark.py \
  --pbp data/raw/game_intelligence/v013/play_by_play.parquet \
  --schedules data/raw/game_intelligence/v013/schedules.parquet \
  --players data/raw/game_intelligence/v013/players.parquet \
  --player-actuals data/raw/game_intelligence/v013/player_stats.parquet \
  --test-season 2023 \
  --test-season 2024 \
  --test-season 2025
```

Or use the manual workflow:

```text
.github/workflows/v013_drive_volume_benchmark.yml
```

The workflow defaults to a cheap **smoke** mode first, then supports a full 2023-2025 replay. It publishes `report.md` into the Actions job summary and uploads immutable benchmark artifacts.

## v0.12 simulated opportunity foundation

v0.12 moved the state-conditioned carry/target allocator into simulated game states and introduced four-cell attribution:

| Variant | Play calling | Opportunity allocation |
|---|---|---|
| `profile_static` | team/opponent profile | static recent share |
| `learned_static` | learned run/dropback head | static recent share |
| `profile_state` | team/opponent profile | state-conditioned allocator |
| `learned_state` | learned run/dropback head | state-conditioned allocator |

It also corrected several evaluation traps:

- carries and targets are scored from actual Monte Carlo draws;
- opportunity uses union scoring so missed roles cannot disappear through an inner join;
- every matchup player receives an explicit row in every simulation, including zero outcomes;
- unrelated league players are excluded from each game's draw matrix;
- context is tested against leave-one-context-out and permutation controls.

The state allocator remains a challenger rather than an assumed champion.

## v0.11 frozen replay and blend foundation

v0.11 established expanding weekly point-in-time replay:

```text
Week N model = every permitted observation strictly before Week N
```

It also introduced the oracle-state `StateConditionedOpportunityModel`, historical direct-vs-generative quantile blending, and stricter multi-season promotion gates.

Archived direct and generative projections can be tested with:

```text
Q_blend = w * Q_direct + (1 - w) * Q_generative
```

Blend weights are learned only from earlier archived predictions.

## v0.10 game-intelligence foundation

v0.10 introduced the point-in-time generative football engine:

- normalized nflverse play-by-play state;
- leakage-safe offense and defense tendency snapshots;
- situational play-call context;
- recency-weighted player usage;
- coaching/play-caller registry contracts;
- learned run/dropback probability challenger;
- hierarchical empirical play outcomes;
- score, clock, possession, down, distance, and field-position simulation;
- correlated raw player stat draws;
- exact league rescoring;
- weekly research refresh and immutable evidence registry.

## League and ranking layer

The fantasy layer applies league scoring before replacement level and VORP whenever sufficient stat components are available.

```text
correlated/provided league draws
        ↓
complete component rescoring
        ↓
generic fantasy-point fallback
```

Sleeper and ESPN league interpretation share one `LeagueConfig`, including multi-QB and superflex handling.

External rankings and ADP are normalized into a timestamped common schema and used as challenger/audit context rather than football truth.

## Research API

```text
GET  /v1/research/game-intelligence/sources
GET  /v1/research/game-intelligence/status
GET  /v1/research/game-intelligence/benchmark
POST /v1/research/game-intelligence/simulate
```

Every research response preserves:

```text
research_only = true
production_projection_changed = false
automatic_promotion = false
```

The benchmark endpoint now reads v0.13 evidence by default. The live simulation endpoint intentionally remains on the established simulator path and does not automatically activate `DriveVolumeModel`.

## Error decomposition

The project treats a fantasy miss as a chain of testable mechanisms:

```text
wrong possession / drive volume
    ↓
wrong team play volume
    ↓
wrong run/pass probability
    ↓
wrong player opportunity allocation
    ↓
wrong completion / rushing / touchdown efficiency
    ↓
wrong fantasy covariance / uncertainty
```

A new model should target the failing layer instead of adding complexity to the entire stack.

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
  scripts/run_v011_blend_benchmark.py \
  scripts/run_v012_factorial_benchmark.py \
  scripts/run_v013_drive_volume_benchmark.py
```

Run the operational API:

```bash
uvicorn player_state_engine.api.operational:app --reload
```

## Repository map

```text
src/player_state_engine/
  game_intelligence/
    benchmark.py          v0.11 expanding frozen replay
    blend.py              direct/generative quantile calibration
    drive.py              v0.13 drive-volume model + diagnostics
    drive_simulator.py    isolated drive-volume simulator probe
    factorial.py          v0.12 four-cell attribution
    opportunity.py        state-conditioned carry/target challenger
    replay.py             frozen game replay primitives
    simulator.py          established research play-by-play state machine
    tendencies.py         team and matchup priors
    usage.py              point-in-time player usage state
    volume_benchmark.py   v0.13 eight-cell replay + v0.14 router
scripts/
  run_v011_game_benchmark.py
  run_v011_blend_benchmark.py
  run_v012_factorial_benchmark.py
  run_v013_drive_volume_benchmark.py
.github/workflows/
  weekly_game_intelligence.yml
  v011_historical_game_benchmark.yml
  v012_factorial_game_benchmark.yml
  v013_drive_volume_benchmark.yml
```

## Modeling rules

1. No random row splits for weekly NFL evaluation.
2. No feature may use information published after the prediction cutoff.
3. No same-game outcome may enter its own feature vector.
4. Retrospective data is not live data merely because it is downloadable.
5. External consensus is a challenger or sensor, not ground truth.
6. Every complex model must beat a simpler baseline on frozen evidence.
7. Calibration and interval coverage matter alongside point accuracy.
8. Contextual feature families require negative controls.
9. Stochastic A/B experiments should isolate RNG streams when possible.
10. No scheduled benchmark automatically promotes a production model.
11. No automatic real-money wagering.
12. When an experiment loses, keep the result and change the hypothesis rather than the scoreboard.

See `docs/modeling/game_intelligence_v013.md`, `docs/modeling/v013_next_development.md`, and `docs/releases/v0.13.md` for the current research contract.
