# NFL Player State Engine v0.14

**Fourth Down Lab** is a leakage-safe probabilistic NFL player-state, game-simulation, fantasy-valuation, and decision-research engine. The repository is built around a simple rule: new modeling complexity does not get authority because it sounds plausible. It has to survive point-in-time replay, simpler baselines, negative controls, calibration checks, and downstream evaluation first.

> Research and entertainment only. The project does not place wagers or promise profit. Predictive, fantasy, and market results should remain timestamped, auditable, and evaluated out of sample.

## System architecture

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
              ┌────────┴────────┐
              ▼                 ▼
        DIRECT PLAYER      FOOTBALL WORLD
            MODEL            SIMULATOR
         q10 / q50 / q90          │
              │                   ▼
              │              DRIVE STATE
              │                   │
              │          ┌────────┴────────┐
              │          ▼                 ▼
              │      PLAY / ROLE      POSSESSION
              │       OUTCOMES        TRANSITIONS
              │          │                 │
              └──────────┴────────┬────────┘
                                  ▼
                           CORRELATED DRAWS
                                  │
                                  ▼
                           EXACT LEAGUE SCORING
                                  │
                                  ▼
                           FROZEN REPLAY LAB
                                  │
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
              CALIBRATION     FACTORIAL        NEGATIVE
                              ATTRIBUTION       CONTROLS
                  │               │               │
                  └───────────────┴───────────────┘
                                  ▼
                            PROMOTION GATES
                                  │
                                  ▼
                         FANTASY DECISION LAYER
```

The project separates five questions that are easy to accidentally mix together:

1. **Player state:** what role, availability, and opportunity does a player have now?
2. **Football state:** what is likely to happen to drives, plays, possessions, and scoring?
3. **League value:** what are those outcomes worth under exact scoring and roster economics?
4. **Acquisition timing:** when is a player likely to disappear in a draft or waiver market?
5. **External evidence:** what can rankings, injuries, coaching changes, practice reports, and markets tell us without becoming truth by default?

# What v0.14 adds

## Possession Transition & Special Teams Laboratory

v0.13 isolated continuing-drive pace and drive-start priors. That exposed the next structural gap: when a drive ended, the research simulator still used fixed transition timings, fixed field-position resets, and a transparent field-goal heuristic.

v0.14 introduces a separate research layer for the boundary between possessions:

```text
CURRENT POSSESSION
      │
      ▼
 TERMINAL EVENT
      │
      ├── touchdown
      ├── turnover
      ├── punt
      ├── made field goal
      ├── missed field goal
      ├── turnover on downs
      ├── halftime
      └── other / fallback
      │
      ▼
TRANSITION CLOCK
      │
      ▼
NEXT POSSESSION START
      │
      ▼
yardline_100 + new offensive state
```

The release remains **research-only**. The established live research simulator and production player projections are not automatically changed.

## 1. Raw-PBP transition evidence

The normal game-intelligence frame intentionally contains offensive scrimmage plays. That is correct for play calling, outcomes, pace, and player allocation, but punts and field goals are frequently separate non-scrimmage rows.

v0.14 therefore builds possession-transition evidence directly from raw play-by-play:

```text
last offensive scrimmage
        ↓
punt / field goal / terminal event
        ↓
return / administrative transition
        ↓
first scrimmage of next possession
```

The resulting transition frame records:

- transition family;
- previous offense;
- next offense;
- source field position;
- next starting field position;
- terminal-event-to-next-play clock runoff when meaningfully observable.

Realized special-teams counts are also computed directly from raw PBP. A final-game punt or field goal therefore cannot disappear from evaluation merely because there is no subsequent offensive possession.

## 2. Hierarchical `PossessionTransitionModel`

The first challenger is deliberately transparent and sample-aware rather than deep.

It learns recency-weighted distributions for:

```text
transition type
    + next offense
    + source field zone
        ↓
next-possession yardline
transition runoff
```

Sparse contexts shrink toward transition-family priors. A tiny sample cannot gain full authority simply because it is more specific.

## 3. Field-goal calibration

The transition layer also contains an empirical field-goal probability challenger.

The current hierarchy begins with distance-bucket make rates and permits team-specific history to move those rates only as evidence accumulates.

It intentionally does **not** yet assume access to:

- kicker-specific state;
- archived weather forecasts;
- roof and surface interactions;
- holder / long-snapper continuity;
- block-unit strength.

Those are future evidence families that must earn inclusion separately.

## 4. Negative controls

A contextual transition model should beat more than a fixed heuristic.

### Transition control

`next_start_yardline_100` and transition timing are shuffled within:

```text
transition type × season
```

This preserves the broad transition distribution and season environment while breaking the contextual relationship the challenger claims to exploit.

### Field-goal control

FG outcomes are shuffled within:

```text
distance bucket × season
```

The challenger must therefore add information beyond the broad historical distance curve.

## 5. Baseline-parity stochastic design

The v0.14 transition probe adds a sixth RNG stream while preserving v0.13's first five component streams:

```text
1. special teams / fourth down
2. play calling
3. play outcomes
4. player allocation
5. drive tempo / v0.13 starts
6. v0.14 possession transitions
```

When v0.14 replaces a v0.13 drive-start draw, the corresponding v0.13 tempo draw is still consumed and discarded. This keeps later continuing-drive pace randomness aligned across A/B cells.

The test suite explicitly checks that:

```text
transition_model = None
        ↓
v0.14 instrumented probe
        ==
frozen v0.13 core game/team/player draws
```

This prevents instrumentation itself from masquerading as model lift.

## 6. Four-cell expanding replay

Learned play calling and state-conditioned player opportunity are held fixed while v0.14 crosses two switches:

| Variant | Drive volume | Possession transitions |
|---|---|---|
| `legacy_drive_legacy_transition` | legacy | legacy |
| `drive_legacy_transition` | v0.13 challenger | legacy |
| `legacy_drive_transition` | legacy | v0.14 challenger |
| `drive_transition` | v0.13 challenger | v0.14 challenger |

The primary v0.14 comparison is:

```text
drive_transition
        vs
drive_legacy_transition
```

Only possession-transition authority changes in that comparison.

Every test week is trained strictly on earlier chronology.

## 7. Isolated and downstream diagnostics

The new isolated laboratory measures:

```text
next-start yardline MAE
transition-time MAE
field-goal log loss
field-goal Brier score
```

against transition-type, distance, and permutation baselines.

The full simulator then measures whether those local improvements survive downstream:

```text
team plays
team pass rate
team points
team drives
plays per drive
continuing-drive pace
starting field position
punts
field-goal attempts
field goals made
turnovers
turnovers on downs
player carries / targets
fantasy pinball / interval coverage
```

A local field-position win cannot hide a scoring or fantasy regression.

## 8. Fail-closed v0.14 gate

`v014_transition_promotion_gate` expects, by default:

- at least three held-out seasons;
- at least 200 replayed games;
- at least 500 isolated possession transitions;
- at least 100 field-goal attempts;
- contextual next-start prediction beating transition-type baseline;
- contextual next-start prediction beating its permutation control;
- transition timing beating type baseline and permutation;
- field-goal calibration not regressing against distance baseline or permutation;
- meaningful full-simulation starting-field improvement;
- majority weekly wins;
- no material regression in team volume, scoring, special teams, player opportunity, or fantasy distribution loss.

Even a completely cleared automated gate means only:

```text
eligible for manual research-champion review
                    ≠
production promotion
```

## 9. Evidence-routed v0.15

v0.15 is deliberately not predetermined.

```text
transition signal + downstream gains
    → latent persistent drive strategy

isolated transitions work, full game does not
    → transition-action generation / drive termination

field-goal calibration weak
    → kicker + weather + stadium state

field position improves, scoring does not
    → decomposed scoring transitions

team play volume remains weak
    → drive continuation / duration hazard

special-teams residual dominates
    → richer punt / kickoff / return evidence

no stable signal
    → collect more replay evidence
```

A sequence transformer remains deferred until transparent state models leave reproducible sequential residuals.

# Run v0.14

Historical runner:

```bash
python scripts/run_v014_transition_benchmark.py \
  --pbp data/raw/game_intelligence/v014/play_by_play.parquet \
  --schedules data/raw/game_intelligence/v014/schedules.parquet \
  --players data/raw/game_intelligence/v014/players.parquet \
  --player-actuals data/raw/game_intelligence/v014/player_stats.parquet \
  --test-season 2023 \
  --test-season 2024 \
  --test-season 2025
```

Manual GitHub Actions workflow:

```text
.github/workflows/v014_transition_benchmark.yml
```

The workflow defaults to an inexpensive smoke mode before the complete 2023–2025 held-out replay. It publishes `report.md` into the Actions summary and retains benchmark evidence artifacts.

# Research lineage

## v0.13 — Drive volume and state

v0.13 added forward-aligned `seconds_to_next_play`, continuing-drive pace modeling, drive-start priors, drive/pace diagnostics, an eight-cell replay, and a pace permutation control.

A critical correction from that release is preserved: `seconds_between_plays` describes time since the previous play, while `seconds_to_next_play` is the valid forward target for post-play runoff.

## v0.12 — Simulated-state opportunity

v0.12 moved state-conditioned carry/target allocation into the actual Monte Carlo state machine and introduced factorial attribution. It also made missed/spurious roles visible with union scoring and explicit zero-stat player × simulation rows.

## v0.11 — Frozen weekly replay

v0.11 established the canonical expanding weekly protocol:

```text
Week N model = every permitted observation strictly before Week N
```

It also introduced oracle-state opportunity diagnostics and historical direct-vs-generative quantile blending.

## v0.10 — Generative football foundation

v0.10 introduced the point-in-time play-by-play research simulator, lagged team tendencies, player usage state, coaching/play-caller evidence, empirical outcomes, correlated raw stat draws, exact league rescoring, and guarded promotion infrastructure.

# League and ranking layer

Football simulation is only one side of the project.

The fantasy layer applies league scoring before replacement level and VORP whenever sufficient stat components are available. Sleeper and ESPN interpretation share a canonical `LeagueConfig`, including multi-QB and superflex formats.

External rankings and ADP are normalized into timestamped evidence and remain challenger/audit signals rather than football truth.

# Research API

```text
GET  /v1/research/game-intelligence/sources
GET  /v1/research/game-intelligence/status
GET  /v1/research/game-intelligence/benchmark
POST /v1/research/game-intelligence/simulate
```

Research responses preserve the boundary:

```text
research_only = true
production_projection_changed = false
automatic_promotion = false
```

The benchmark endpoint defaults to v0.14 evidence. The live simulation endpoint intentionally remains on the established simulator path and does not automatically activate the new transition challenger.

# Installation

```bash
python -m pip install -e '.[dev,intelligence,api]'
```

Run tests:

```bash
pytest
```

Lint package and operational research scripts:

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
  scripts/run_v013_drive_volume_benchmark.py \
  scripts/run_v014_transition_benchmark.py
```

Run the operational API:

```bash
uvicorn player_state_engine.api.operational:app --reload
```

# Repository map

```text
src/player_state_engine/
  game_intelligence/
    benchmark.py             v0.11 expanding frozen replay
    blend.py                 direct/generative quantile calibration
    factorial.py             v0.12 play-call/opportunity attribution
    opportunity.py           state-conditioned carry/target allocation
    drive.py                 v0.13 drive-volume model
    drive_simulator.py       v0.13 mechanism-isolated simulator probe
    transition.py            v0.14 raw transition evidence + model
    transition_simulator.py  v0.14 transition-instrumented simulator
    transition_benchmark.py  v0.14 expanding four-cell replay
    replay.py                frozen game replay primitives
    simulator.py             established research simulator
    tendencies.py            point-in-time team/matchup priors
    usage.py                 point-in-time player usage state

scripts/
  run_v011_game_benchmark.py
  run_v011_blend_benchmark.py
  run_v012_factorial_benchmark.py
  run_v013_drive_volume_benchmark.py
  run_v014_transition_benchmark.py

.github/workflows/
  weekly_game_intelligence.yml
  v011_historical_game_benchmark.yml
  v012_factorial_game_benchmark.yml
  v013_drive_volume_benchmark.yml
  v014_transition_benchmark.yml
```

# Modeling rules

1. No random row splits for weekly NFL evaluation.
2. No feature may use information published after the prediction cutoff.
3. No same-game outcome may enter its own prediction-time feature vector.
4. Retrospective data is not live data merely because it is downloadable.
5. External consensus is a challenger or sensor, not ground truth.
6. Every complex model must beat a simpler baseline on frozen evidence.
7. Calibration and interval coverage matter alongside point accuracy.
8. Contextual feature families require negative controls.
9. Stochastic A/B experiments should isolate random streams and verify baseline parity.
10. Local metric wins must survive downstream simulation metrics.
11. No scheduled benchmark automatically promotes a production model.
12. No automatic real-money wagering.
13. When an experiment loses, preserve the result and change the hypothesis rather than the scoreboard.

See:

- `docs/modeling/game_intelligence_v014.md`
- `docs/modeling/v014_experiment_queue.md`
- `docs/releases/v0.14.md`
