# Player State Graph 2.0 research program

## Status

**Research authority only.** This program is intentionally parallel to the frozen v0.16 terminal-family experiment contract. It does not rename itself v0.17 and it cannot replace the current direct quantile champion without clearing the evidence gates in `state_graph.experiments`.

## Why this exists

The strongest lesson from the 2021-2025 direct benchmark is structural: position-specific carries improved dramatically when the football problem was reformulated correctly. The next research spine therefore models explicit football states instead of adding another opaque direct fantasy-points estimator.

```text
ACTIVE?
  -> TEAM VOLUME
  -> PLAYER PARTICIPATION
  -> OPPORTUNITY SHARE
  -> EXECUTION
  -> RAW FOOTBALL STATS
  -> EXACT LEAGUE SCORING
```

The direct player model, the generative game world, and external consensus remain separate experts. The graph is a fourth auditable layer until historical evidence says otherwise.

## Implemented modules

| Module | Responsibility | Default authority |
|---|---|---|
| `role.py` | discounted Beta role posteriors and discontinuity scores | research |
| `regime.py` | explicit QB/coach/OL/team/rookie/injury/scheme regime boundaries | research |
| `provenance.py` | publication-time availability and leakage enforcement | infrastructure |
| `evidence.py` | source-family -> latent-variable routing contract | infrastructure |
| `builder.py` | construct availability, team volume, role, execution and regime state | research |
| `coherent.py` | coherent football-stat Monte Carlo and exact league rescoring | research |
| `calibration.py` | recency-weighted position x target conformal intervals with fallback | challenger |
| `fusion.py` | historically learned hierarchical expert blending | challenger |
| `uncertainty.py` | latent-source uncertainty decomposition | explanatory |
| `insights.py` | intelligence cards, scenario explorer, change attribution, upside paths | product |
| `season_sim.py` | legal lineups, H2H + median standings, playoffs, titles, transaction deltas | product/research |
| `experiments.py` | paired block bootstrap, FDR ledger, evidence tiers, fail-closed promotion | infrastructure |
| `tracking_distillation.py` | tracking data as a teacher for live-available proxy signals | research |

## Dynamic role state

`DiscountedBetaRoleEstimator` maintains posterior states for:

- snap share;
- route participation;
- target share;
- carry share;
- red-zone share;
- goal-line share;
- third-down share;
- two-minute share.

Every forecast is point-in-time. The estimator first cuts history at the forecast week and only then computes recency weights. Each metric exposes posterior mean/std, effective evidence, recent trend and a bounded change score. `DynamicRoleState` also exposes aggregate role-change probability and `LOW/MEDIUM/HIGH` maturity.

The change score is deliberately an evidence score rather than a causal probability. It combines standardized surprise against the pre-update posterior with short-window slope. That makes a 30% -> 70% role jump visible without pretending the engine knows why it happened.

## Regime state

`RegimeDetector` treats the following as explicit non-stationarity boundaries:

- QB starter change;
- play-caller change;
- head-coach change;
- major OL change;
- team change;
- rookie transition;
- major role injury;
- scheme change;
- season boundary.

The state tracks weeks since the latest boundary and smoothly shifts weight from historical priors to current-regime evidence. Early-season and post-injury slices should be evaluated separately.

## Publication-time provenance

A retrospective row is not automatically a legal pregame feature. `SourceAvailabilityRecord` carries:

```text
event_time
published_at
first_observed_at
retrieved_at
available_for_prediction_at
source_family
coverage
license
```

The leakage rule is:

```text
available_for_prediction_at <= prediction_cutoff
```

This is stricter than event-time semantics and is required for all future live/replay source families.

## Evidence routing, not feature dumping

`LatentEvidenceRouter` makes evidence-family scope explicit. Examples:

- official injury/practice -> availability;
- snap counts/depth chart -> participation;
- routes/alignment/structured coach claims -> opportunity;
- weather/market environment -> environment;
- tracking teacher -> execution/environment research proxies.

Unknown families fail closed. Broad player-personality inference has no allowed route. Public/social material can only enter after it has been converted into a structured factual claim with a specific latent target and point-in-time timestamp.

## Coherent forecast graph

`PlayerStateGraphSampler` samples the football process before scoring fantasy points. Skill-player draws preserve constraints such as:

```text
receptions <= targets <= routes
targets <= team targets
carries <= team rushes
inactive -> zero player production
```

The joint-team sampler shares team volume and allocates targets/carries through normalized player role shares so teammates compete for the same opportunity pool.

Fantasy points are never independently predicted inside this layer. Draws are passed to `fantasy.scoring.score_simulation_draws`, which applies the exact `LeagueConfig` scoring weights.

## Conditional calibration

`RecencyWeightedConditionalConformal` calibrates q10/q90 intervals from older forecast errors. The hierarchy is:

```text
position x target
  -> target
  -> global
```

Recent calibration errors receive more weight. Coverage and interval width are reported together, so the system cannot claim victory by making every interval enormous.

## Forecast fusion

`HierarchicalForecastFusion` expects archived forecasts in long form for experts such as:

```text
direct
world
consensus
player_state_graph
```

Weights are learned only from historical predictions. Local weights shrink through:

```text
global
  -> position
  -> position x target
  -> + forecast horizon
  -> + regime maturity
```

The returned diagnostics retain expert medians, weights and disagreement rather than hiding the disagreement inside one number.

## Uncertainty decomposition

`decompose_counterfactual_variance` is designed for common-random-number nested Monte Carlo. Generate the normal total draw, then regenerate while one latent family is held to its central value. Variance reduction is attributed to:

- availability;
- team volume;
- role/opportunity;
- execution;
- matchup/environment;
- residual model uncertainty.

Because interacting sources can overlap, shares are normalized and must be labeled model uncertainty decomposition, not causal attribution.

## Insight engine

`PlayerIntelligenceCard` can expose:

- median and q10-q90;
- top-12/top-24 probability when thresholds are supplied;
- bust probability versus replacement;
- active probability;
- expected routes, targets and red-zone opportunities;
- role state and role-change score;
- projection confidence;
- consensus disagreement;
- evidence freshness;
- uncertainty shares.

Projection-change attribution is explicitly labeled **model attribution, not causal truth**. `compare_scenarios` supports alternate teammate/QB/availability worlds, and `upside_path` describes the opportunity states most commonly associated with a high fantasy outcome.

## Rest-of-season fantasy simulation

`FantasySeasonSimulator` consumes already-correlated weekly player draws and a real `LeagueConfig`.

For every Monte Carlo world it:

1. optimizes a legal lineup for each manager/week;
2. scores head-to-head matchups;
3. optionally adds median-game wins using `median_scoring` and `median_game_weight`;
4. builds standings with points as a tiebreaker;
5. seeds 2/4/6/8-team playoff brackets;
6. resolves the bracket from the same weekly worlds;
7. reports expected wins/points, playoff probability, championship probability and expected seed.

`transaction_delta` reruns the exact same worlds under before/after rosters, yielding decision-unit changes rather than additive player-value approximations.

## Experiment authority

Evidence tiers are encoded in `EvidenceTier`:

| Tier | Meaning |
|---:|---|
| 0 | synthetic only |
| 1 | single historical slice |
| 2 | multi-season isolated |
| 3 | multi-season downstream |
| 4 | live shadow season |
| 5 | decision-value validated |

`PromotionPolicy` fails closed on insufficient tier, effect, confidence interval, slice consistency, coverage, live data availability, negative controls or FDR. A feature cannot gain more authority than its evidence tier permits.

## Running a research forecast

Prepare a weekly history table and forecast rows with at least:

```text
history:
player_id, season, week, team, position
role shares and football stats when available
team_plays, team_dropbacks when available

forecast rows:
player_id, season, week, opponent
optional player_name, prediction_cutoff
```

Then run:

```bash
python scripts/run_player_state_graph_research.py \
  --history data/processed/player_week_history.parquet \
  --forecast-rows data/processed/forecast_rows.parquet \
  --league-config config/leagues/my_league.yaml \
  --simulations 5000 \
  --output-dir artifacts/player_state_graph/my_league
```

Artifacts include coherent scored draws, dynamic role states, forecast summaries and player intelligence cards.

## Required benchmark sequence

The next evidence program is ordered, not aspirational:

1. finish the v0.16 smoke/full replay required by its existing contract;
2. rebuild the direct 2021-2025 benchmark under publication-time provenance;
3. evaluate dynamic role state as an isolated challenger;
4. evaluate conditional calibration by target/position with coverage + sharpness;
5. compare direct vs graph using the same held-out player-weeks;
6. add world/consensus experts only after archived-prediction parity is verified;
7. evaluate full fusion;
8. evaluate season-level lineup/waiver/trade decisions;
9. run 2026 Wednesday/Sunday shadow snapshots;
10. only then consider production authority.

## Explicitly deferred

The following remain lower-priority until the above earns evidence:

- broad social/personality inference;
- transformer world models;
- raw tracking as a production dependency.

Tracking can teach proxy representations through `TrackingTeacherDistiller`; it cannot bypass the point-in-time or evidence-tier rules.
