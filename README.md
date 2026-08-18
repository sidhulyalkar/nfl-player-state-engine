# NFL Player State Engine v0.12

**Fourth Down Lab** is a leakage-safe, probabilistic NFL player-state and fantasy decision system. The project combines a direct player projection engine with a guarded generative game simulator, then forces new complexity through frozen historical replay before it can affect production decisions.

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
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   CALIBRATION     FACTORIAL      BLEND TESTS
                  ATTRIBUTION
        │              │              │
        └──────────────┴──────────────┘
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

## What v0.12 adds

### 1. State-conditioned opportunity inside simulated game states

The carry/target allocator can now run on the simulator's own evolving down, distance, field position, clock, red-zone and score state. It remains opt-in and research-only.

Historical player identities are filtered through the current point-in-time usage pool before a simulated opportunity is allocated, so stale players cannot receive work merely because they remain in training history.

### 2. Four-cell factorial replay

Every frozen weekly fold can compare:

| Variant | Play calling | Opportunity allocation |
|---|---|---|
| `profile_static` | team/opponent profile | static recent share |
| `learned_static` | learned run/dropback head | static recent share |
| `profile_state` | team/opponent profile | state-conditioned allocator |
| `learned_state` | learned run/dropback head | state-conditioned allocator |

The four variants share the same point-in-time evidence, empirical outcome model, matchup, usage state and simulation seed. This lets replay estimate the marginal value of play calling, allocation, and their combination instead of changing several mechanisms at once.

### 3. Opportunity evaluation from the actual Monte Carlo draws

The simulator now records `carries` and `targets` in each player draw. Replay scores those realized simulated opportunities directly.

Player opportunity evaluation also uses the union of predicted and observed players. Completely missing a real role, or inventing a material role that did not occur, is now penalized rather than disappearing through an inner join. Reports expose observed-player coverage alongside carry, target and combined opportunity MAE.

### 4. Context ablations and a negative control

The opportunity lab compares static share, red-zone-only context, full context, leave-one-context-out variants, and a within-team-season context permutation.

The permutation preserves chronology, team/player identities and base opportunity counts while breaking the relationship between play state and context. A context model must beat that control before it deserves more authority.

### 5. Evidence-routed next development

The v0.12 report does not merely output scores. It classifies the likely next bottleneck:

```text
allocation wins + fantasy improves -> richer route / alignment / role evidence
oracle context wins but full simulation loses -> pace and drive-state realism
play-call improves but team volume does not -> pace / drive volume
opportunity improves but scoring does not -> decomposed play outcomes
context fails permutation control -> reject / redesign context model
unstable by season -> evidence maturity / regime segmentation
```

This router is comparative research triage, not an automatic architecture selector.

Run the full experiment with:

```bash
python scripts/run_v012_factorial_benchmark.py \
  --pbp data/raw/game_intelligence/v012/play_by_play.parquet \
  --schedules data/raw/game_intelligence/v012/schedules.parquet \
  --players data/raw/game_intelligence/v012/players.parquet \
  --player-actuals data/raw/game_intelligence/v012/player_stats.parquet \
  --test-season 2023 \
  --test-season 2024 \
  --test-season 2025
```

Or use the manual workflow:

```text
.github/workflows/v012_factorial_game_benchmark.yml
```

No factorial result can alter production automatically.

## v0.11 frozen replay and blend foundation

v0.11 established expanding weekly point-in-time replay:

```text
Week N model = every permitted observation strictly before Week N
```

It also introduced the oracle-state `StateConditionedOpportunityModel`, historical direct-vs-generative quantile blending, and stricter multi-season promotion gates. The oracle-state benchmark deliberately isolated player allocation from team-volume/run-pass error before v0.12 moved the allocator into simulated states.

Archived direct-model and game-simulator predictions can be tested with:

```text
Q_blend = w * Q_direct + (1 - w) * Q_generative
```

Blend weights are learned only from earlier archived predictions. Position-specific weights require sufficient evidence and otherwise fall back to a global weight.

## v0.10 game intelligence foundation

v0.10 introduced the point-in-time generative football engine:

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

The simulator remains research-only until frozen replay earns promotion.

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

The live research simulation endpoint intentionally remains on the established static-allocation artifact path. The v0.12 allocator must clear factorial historical replay before being packaged into the weekly live research champion.

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

v0.12 makes the middle layers more independently measurable. If contextual player allocation is useful only when the real state path is known, the next problem is state/volume simulation rather than another allocation formula. If opportunity improves but fantasy scoring does not, the outcome model becomes the clearer target.

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

These are **experiment families**, not trusted model inputs. Every one needs timestamp provenance, an isolated frozen ablation, a negative control, and full downstream replay.

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
  scripts/run_v012_factorial_benchmark.py
```

Run the operational API:

```bash
uvicorn player_state_engine.api.operational:app --reload
```

## Repository map

```text
src/player_state_engine/
  game_intelligence/
    benchmark.py       expanding v0.11 frozen replay
    blend.py           direct/generative quantile calibration
    factorial.py       v0.12 four-cell attribution + evidence router
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
  run_v012_factorial_benchmark.py
  weekly_game_intelligence_refresh.py
.github/workflows/
  weekly_game_intelligence.yml
  v011_historical_game_benchmark.yml
  v012_factorial_game_benchmark.yml
```

## Modeling rules

1. No random row splits for weekly NFL evaluation.
2. No feature may use information published after the prediction cutoff.
3. No same-game outcome may enter its own feature vector.
4. Retrospective data is not live data merely because it is downloadable.
5. External consensus is a challenger or sensor, not ground truth.
6. Every complex model must beat a simpler baseline on frozen evidence.
7. Calibration and interval coverage matter alongside point accuracy.
8. Negative controls are required for contextual feature families.
9. No automatic production promotion from a scheduled workflow.
10. No automatic real-money wagering.
11. When an experiment loses, keep the result and change the hypothesis rather than the scoreboard.

See `docs/releases/v0.12.md` and `docs/modeling/v012_next_development.md` for the current research contract and evidence-routed development plan.
