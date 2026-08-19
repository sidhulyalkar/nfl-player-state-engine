# NFL Player State Engine v0.15

**Fourth Down Lab** is a leakage-safe probabilistic NFL player-state, fantasy-valuation, game-simulation, draft-decision, and continual-learning research engine.

Its governing rule is simple: **a new model does not gain authority because it is plausible or sophisticated. It has to beat timestamp-safe baselines, negative controls, calibration tests, and downstream replay first.**

> Research and entertainment only. The project does not place wagers or promise profit. Predictive, fantasy, and market results should remain timestamped, auditable, and evaluated out of sample.

## Architecture

```text
POINT-IN-TIME EVIDENCE
        │
        ├────────────── player / role state
        ├────────────── team state
        ├────────────── coach / play-caller state
        └────────────── game environment
                         │
                         ▼
                  FOOTBALL WORLD MODEL
                         │
             ┌───────────┼────────────┐
             ▼           ▼            ▼
        PLAY CALL     PLAYER       DRIVE / PACE
                     ALLOCATION        │
             │           │            │
             └──────┬────┘            │
                    ▼                 │
               PLAY OUTCOME           │
                    │                 │
                    ▼                 │
              FOURTH-DOWN POLICY  ← v0.15
                    │
                    ▼
            POSSESSION TRANSITION ← v0.14
                    │
                    ▼
                NEXT GAME STATE
                    │
                    ▼
             CORRELATED MONTE CARLO
                    │
                    ▼
              EXACT LEAGUE SCORING
                    │
                    ▼
               FROZEN REPLAY LAB
        ┌───────────┼───────────┬───────────┐
        ▼           ▼           ▼           ▼
   CALIBRATION   FACTORIAL   NEGATIVE    DOWNSTREAM
                             CONTROLS     FANTASY/GAME
```

A separate direct player model produces player quantiles. The generative simulator is a challenger and explanatory world model, not a replacement by default.

## What v0.15 adds

### Fourth-down decision policy

The simulator previously used a hand-written fourth-down heuristic. v0.15 introduces `FourthDownDecisionModel`, a transparent recency-weighted hierarchical policy over:

- `GO`
- `PUNT`
- `FIELD_GOAL`

State uses only information available at the decision: offense, opponent, yards to go, field position, clock, score differential, and broad context buckets.

The frozen v0.14 heuristic remains an explicit comparator with analytic probabilities, so held-out log loss and Brier score measure whether the learned policy is actually better.

### Drive-termination hazard

`DriveTerminationHazardModel` estimates whether the current offensive scrimmage play ends the drive.

In v0.15 it is deliberately **diagnostic-only**. A binary hazard does not identify whether a terminal event should be a touchdown, turnover, turnover on downs, or another terminal family. The model may earn evidence for the next experiment, but it cannot invent terminal events in Monte Carlo yet.

### Component-isolated RNG

`simulate_matchup_decision_probe` adds a seventh RNG stream for fourth-down policy while preserving v0.14's first six streams.

When the learned decision model is enabled, the frozen heuristic is still evaluated so the random numbers it would have consumed are consumed and discarded. This prevents unrelated special-teams randomness from masquerading as model lift.

**Parity contract:** with the decision model disabled, v0.15 must reproduce the frozen v0.14 core game, team, and player draws under the same seed.

### Four-cell attribution

The v0.15 benchmark crosses transition authority and decision authority while keeping learned play calling, state-conditioned opportunity, and drive-volume modeling fixed:

| Variant | Possession transition | Fourth-down policy |
|---|---:|---:|
| `legacy_transition_legacy_decision` | off | heuristic |
| `legacy_transition_decision` | off | learned |
| `transition_legacy_decision` | learned | heuristic |
| `transition_decision` | learned | learned |

Primary comparison:

```text
transition_decision
vs
transition_legacy_decision
```

Only fourth-down policy authority changes.

## v0.15 evidence layers

### 1. Isolated policy replay

Metrics:

- multiclass log loss
- multiclass Brier score
- action accuracy
- frozen heuristic log loss / Brier
- team-base log loss
- context-base log loss
- season/field-zone/distance permutation control

### 2. Isolated drive-termination replay

Metrics:

- binary log loss
- Brier score
- team-base log loss
- context-base log loss
- season/down/field-zone permutation control

### 3. Full generative replay

Metrics retain the earlier game-intelligence scorecard and add fourth-down decision diagnostics:

- fourth-down decision count MAE
- fourth-down go-attempt MAE
- punts MAE
- field-goal attempt / make MAE
- turnovers on downs MAE
- team plays MAE
- drives MAE
- plays per drive MAE
- pace MAE
- starting field-position MAE
- team points MAE
- player opportunity MAE
- fantasy median / pinball / coverage metrics when actual outcomes are supplied

## Promotion philosophy

`v015_decision_promotion_gate` fails closed unless the challenger has sufficient multi-season evidence and:

- beats the frozen heuristic in isolated log loss;
- beats the permutation control;
- does not regress Brier calibration;
- improves simulated fourth-down go frequency;
- avoids material regression in special teams, volume, scoring, opportunity, or fantasy distributions;
- wins consistently across weeks rather than through one pooled pocket.

Even a cleared gate means only **eligible for manual research-champion review**.

Production projections do not change automatically.

## Historical benchmark

The manual workflow is:

```text
.github/workflows/v015_decision_benchmark.yml
```

Recommended sequence:

1. run `smoke` mode;
2. acquire 2021–2025 history;
3. hold out 2023–2025;
4. replay Weeks 1–18;
5. begin at 15 simulations per game/variant;
6. increase Monte Carlo draws only if paired comparisons remain noisy;
7. use the generated v0.16 router rather than choosing the next model by novelty.

Local runner:

```bash
python scripts/run_v015_decision_benchmark.py \
  --pbp data/raw/game_intelligence/v015/play_by_play.parquet \
  --schedules data/raw/game_intelligence/v015/schedules.parquet \
  --test-season 2023 \
  --test-season 2024 \
  --test-season 2025 \
  --week-start 1 \
  --week-end 18 \
  --simulations-per-game 15 \
  --output-dir artifacts/game_intelligence/v015
```

Outputs:

- `weekly_decision_factorial_metrics.parquet`
- `weekly_decision_isolated_metrics.parquet`
- `summary.json`
- `report.md`

## Research API

The operational API exposes benchmark artifacts read-only:

```text
GET /v1/research/game-intelligence/status
GET /v1/research/game-intelligence/benchmark
GET /v1/research/game-intelligence/sources
POST /v1/research/game-intelligence/simulate
```

The benchmark root defaults to:

```text
artifacts/game_intelligence/v015
```

The live simulation endpoint remains on the established simulator path. It does not silently use v0.15 research challengers.

## Version progression

- **v0.8** — operational Draft War Room and empirical draft-survival challenger
- **v0.9** — ranking calibration, exact scoring, evidence fusion, scarcity and replay
- **v0.10** — play-by-play game simulator and continual-learning infrastructure
- **v0.11** — expanding weekly replay, opportunity challenger, quantile-blend lab
- **v0.12** — factorial attribution and simulated-state opportunity testing
- **v0.13** — drive-volume / pace layer with component-isolated replay
- **v0.14** — possession-transition and special-teams laboratory
- **v0.15** — fourth-down decision policy and diagnostic drive-termination hazard

## Code map

```text
src/player_state_engine/
├── api/
├── fantasy/
├── game_intelligence/
│   ├── benchmark.py
│   ├── blend.py
│   ├── decision.py                 # v0.15
│   ├── decision_benchmark.py       # v0.15
│   ├── decision_simulator.py       # v0.15
│   ├── drive.py
│   ├── drive_simulator.py
│   ├── evaluation.py
│   ├── factorial.py
│   ├── models.py
│   ├── opportunity.py
│   ├── play_features.py
│   ├── replay.py
│   ├── simulator.py
│   ├── tendencies.py
│   ├── transition.py
│   ├── transition_benchmark.py
│   ├── transition_simulator.py
│   └── usage.py
└── ...
```

## Next research routes

The v0.16 router can recommend:

- latent drive strategy state;
- fourth-down execution outcomes;
- richer coach / timeout / environment context;
- explicit terminal-family generation;
- decomposed scoring transitions;
- special-teams player/environment state;
- more replay evidence.

A deep sequence model remains downstream of those transparent tests. The project is trying to build a better probabilistic football world, not win a parameter-count contest.

See:

- `docs/modeling/fourth_down_decision_v015.md`
- `docs/modeling/v015_experiment_queue.md`
- `docs/releases/v0.15.md`
