# NFL Player State Engine v0.16

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
                    │
                    ▼
            TERMINAL FAMILY       ← v0.16
                    │
                    ▼
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

A separate direct player model produces player quantiles. The generative simulator remains a challenger and explanatory world model, not a replacement by default.

## What v0.16 adds

### Canonical terminal-family generation

v0.15 could estimate whether a possession was likely to end, but a binary hazard cannot say *how* it ends. v0.16 introduces `TerminalFamilyModel` over:

- `CONTINUE`
- `SCORE`
- `TURNOVER`
- `DOWNS`
- `END_HALF`

The model is deliberately two-stage:

```text
P(possession ends | observable state)
                 ×
P(terminal family | possession ends, observable state)
```

This prevents the common `CONTINUE` class from hiding a weak terminal-type model.

### Simulator-matched football labels

The canonical labels mirror the frozen simulator's realized ordering:

1. score if the play produces a touchdown or crosses the goal line;
2. otherwise turnover if the play loses possession;
3. otherwise turnover on downs if a fourth-down play fails to convert;
4. otherwise `END_HALF` only when the play is the final eligible possession event before halftime or game end;
5. otherwise `CONTINUE`.

A failed third down followed by a punt or field-goal attempt remains `CONTINUE` because fourth-down policy still owns the next action.

First-down realization uses both the explicit first-down field and yards gained relative to distance, matching the simulator instead of relying on one potentially sparse source column.

### Historically coherent terminal outcomes

v0.16 extends `EmpiricalPlayOutcomeModel` with an additive terminal-family index while leaving the established `sample()` path unchanged.

When research terminal authority is enabled:

1. the simulator samples the terminal family;
2. it samples a historical outcome row compatible with that family;
3. completion, yards, touchdown, turnover, interception, fumble and first-down fields therefore remain coupled to an observed football outcome;
4. if compatible support is unavailable, the exact frozen legacy outcome is used and the fallback is counted.

The model never converts a class label directly into invented player statistics.

### Structural legality

Generative support is masked before sampling:

- `DOWNS` is illegal before fourth down;
- `END_HALF` is illegal outside a short true half/game boundary window.

If a sparse learned distribution places all mass on illegal terminal families, fallback normalization occurs **only across structurally legal families**.

### Common-random-number attribution

The exact v0.15 empirical outcome draw is still consumed on every play. Terminal-family selection and family-conditioned outcome sampling use deterministic shadow RNG streams derived from the pre-draw state.

That means the intervention can change the play while preserving the established legacy RNG trajectory for later plays.

When terminal conditioning falls back, the benchmark records the family that actually materialized from the frozen outcome. Requested and realized family counts are tracked separately.

### Realized-only downstream scoring

The full-simulation benchmark does not grade the model on the terminal family it *asked for*.

Team terminal metrics are reconstructed from the football events that actually happened in the Monte Carlo draw:

- scoring events;
- turnovers;
- turnovers on downs;
- non-clock terminal events.

Requested-vs-realized family mismatch is diagnostic evidence and becomes a promotion blocker rather than a hidden source of optimistic scoring.

## Eight-cell factorial replay

v0.16 crosses three authority switches:

| Axis | Frozen cell | Challenger cell |
|---|---|---|
| Possession transition | legacy | learned |
| Fourth-down decision | heuristic | learned |
| Terminal family | legacy outcome | state-conditioned terminal family |

This creates eight variants. Terminal-family lift is measured within four different parent world-model contexts instead of only in the most favorable fully learned stack.

Learned play calling, state-conditioned player opportunity, and v0.13 drive-volume logic remain fixed.

## Evidence layers

### 1. Isolated terminal replay

Metrics include:

- multiclass log loss;
- multiclass Brier score;
- top-label calibration error;
- per-family Brier and recall;
- canonical termination Brier/log loss;
- conditional terminal-family log loss and accuracy.

Negative controls include:

- full terminal labels permuted within broad season/down/field-zone strata;
- terminal type permuted while exact termination labels remain fixed.

### 2. Generative replay

The existing world-model scorecard remains active:

- team plays MAE;
- drives and plays-per-drive MAE;
- pace MAE;
- starting field-position MAE;
- team points MAE;
- punts and field-goal MAE;
- fourth-down decision MAE;
- player carry / target / opportunity MAE;
- fantasy median / pinball / interval metrics when actuals are provided;
- realized terminal-family event MAE;
- conditioning fallback rate;
- requested-vs-realized mismatch rate.

## Promotion philosophy

`v016_terminal_promotion_gate` fails closed unless the challenger has sufficient multi-season evidence and:

- beats the observable-state terminal baseline;
- beats both permutation controls;
- remains calibrated;
- keeps conditioned-outcome fallback below the safety ceiling;
- has zero requested-vs-realized semantic mismatch under the tested contract;
- improves realized non-clock terminal frequency in most parent contexts;
- wins consistently across held-out weeks;
- avoids material regression in volume, pace, scoring, opportunity, fantasy, special teams, or fourth-down behavior.

Even a cleared gate means only **eligible for manual research-champion review**.

Production projections and the default live simulator do not change automatically.

## Historical benchmark

Manual workflow:

```text
.github/workflows/v016_terminal_benchmark.yml
```

Recommended sequence:

1. run `smoke` mode;
2. acquire 2021-2025 source history;
3. hold out 2023-2025;
4. replay Weeks 1-18 with expanding point-in-time folds;
5. begin with a modest number of simulations because eight variants multiply Monte Carlo cost;
6. increase draws only if paired estimates remain noisy;
7. route v0.17 from evidence rather than architecture novelty.

Local runner:

```bash
python scripts/run_v016_terminal_benchmark.py \
  --pbp data/raw/game_intelligence/v016/play_by_play.parquet \
  --schedules data/raw/game_intelligence/v016/schedules.parquet \
  --test-season 2023 \
  --test-season 2024 \
  --test-season 2025 \
  --week-start 1 \
  --week-end 18 \
  --simulations-per-game 8 \
  --output-dir artifacts/game_intelligence/v016
```

Outputs:

- `weekly_terminal_factorial_metrics.parquet`
- `weekly_terminal_isolated_metrics.parquet`
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
artifacts/game_intelligence/v016
```

The live `/simulate` endpoint deliberately remains on the established non-terminal-authority path. A version bump is not a model promotion.

## Version progression

- **v0.8** - operational Draft War Room and empirical draft-survival challenger
- **v0.9** - ranking calibration, exact scoring, evidence fusion, scarcity and replay
- **v0.10** - play-by-play game simulator and continual-learning infrastructure
- **v0.11** - expanding weekly replay, opportunity challenger, quantile-blend lab
- **v0.12** - factorial attribution and simulated-state opportunity testing
- **v0.13** - drive-volume / pace layer with component-isolated replay
- **v0.14** - possession-transition and special-teams laboratory
- **v0.15** - fourth-down decision policy and diagnostic drive-termination hazard
- **v0.16** - terminal-family generation, coherent conditioned outcomes, and eight-cell attribution

## Code map

```text
src/player_state_engine/
├── api/
├── fantasy/
├── game_intelligence/
│   ├── benchmark.py
│   ├── decision.py
│   ├── decision_benchmark.py
│   ├── decision_simulator.py
│   ├── drive.py
│   ├── drive_simulator.py
│   ├── models.py
│   ├── opportunity.py
│   ├── simulator.py
│   ├── terminal.py                 # v0.16
│   ├── terminal_benchmark.py       # v0.16
│   ├── terminal_simulator.py       # v0.16
│   ├── transition.py
│   ├── transition_benchmark.py
│   └── transition_simulator.py
└── ...
```

## v0.17 evidence routes

`recommend_v017_development` can route toward:

- latent drive strategy state;
- decomposed scoring execution;
- richer terminal-family context;
- terminal-authority mechanics audit;
- drive strategy / continuation state;
- additional replay evidence.

A deep sequence model remains downstream of these transparent tests. The objective is a better probabilistic football world, not a larger pile of parameters wearing shoulder pads.

## Validation boundary

Current v0.16 implementation validation includes:

- Ruff passing;
- full Python compilation passing;
- **151 Python tests passing**;
- frontend production build passing;
- v0.15 parity tests;
- sparse structural-support tests;
- deterministic shadow-RNG tests;
- requested-vs-realized accounting tests;
- synthetic eight-cell replay tests.

Those checks establish software and experimental-contract integrity. They do **not** establish historical predictive lift. The next scientific milestone is the real expanding v0.16 replay.

See:

- `docs/modeling/terminal_family_v016.md`
- `docs/modeling/v016_experiment_queue.md`
- `docs/releases/v0.16.md`
