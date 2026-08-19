# Player State Graph research spine

Status: **implemented as a research challenger, not promoted to production**.

This package implements the next forecasting program in parallel with the frozen v0.16 game-world experiment. It deliberately does **not** rename the repository to v0.17, change the production champion, or grant new intelligence families authority before historical evidence exists.

## Why this exists

The direct production engine predicts useful player quantiles, while v0.10-v0.16 built an increasingly structured game-world simulator. The Player State Graph connects those two lines of research through explicit latent player states:

```text
                 AVAILABILITY
                      |
                      v
                  TEAM VOLUME
                      |
                      v
             PLAYER PARTICIPATION
                      |
                      v
              OPPORTUNITY SHARE
                      |
                      v
                  EXECUTION
                      |
                      v
             RAW FOOTBALL STATS
                      |
                      v
             EXACT LEAGUE SCORING
```

The graph is intended to make forecasts more coherent and easier to audit. A receiver cannot catch more passes than targets in a normal draw, fantasy points are scored from sampled football outcomes, and uncertainty can be traced to role, availability, environment, volume, execution, or residual model variance.

## Code map

| Module | Responsibility |
|---|---|
| `player_state/core.py` | Point-in-time evidence, dynamic role posteriors, change detection, regime maturity |
| `player_state/graph.py` | Coherent player-stat Monte Carlo, league scoring, uncertainty decomposition |
| `player_state/forecasting.py` | Recency-weighted conditional conformal calibration and hierarchical multi-expert fusion |
| `player_state/insights.py` | Player Intelligence Card, rank probabilities, scenarios, upside paths, projection-change attribution |
| `player_state/season.py` | Correlated rest-of-season lineup, standings, playoff, and championship simulation |
| `player_state/experiments.py` | Evidence tiers, paired block bootstrap, consistency checks, FDR helper |
| `player_state/service.py` | Stable orchestration boundary for API/CLI/product consumers |

## 1. Publication-time provenance

`TemporalEvidenceRecord` distinguishes:

- `event_time`
- `published_at`
- `first_observed_at`
- `retrieved_at`
- `available_for_prediction_at`
- `source_family`
- `coverage`
- `license`

The leakage rule is:

```text
available_for_prediction_at <= prediction_cutoff
```

An old football event that was published after the prediction cutoff is unavailable to the replay. Invalid timestamp order fails closed.

## 2. Dynamic role state

`DynamicRoleFilter` tracks Beta posteriors for:

- snap share
- route participation
- target share
- carry share
- red-zone share
- goal-line share
- third-down share
- two-minute share

The state estimator uses position priors, exponentially discounts old evidence, and reports:

- posterior mean
- q10 / q50 / q90
- effective sample size
- maturity
- change probability

A sharp usage observation is measured against the pre-update posterior and sampling variance. This is a transparent change detector, not a black-box label.

All updates are gated by `available_for_prediction_at`.

## 3. Regime state

`RegimeTracker` represents discontinuities such as:

- QB starter change
- play-caller change
- head-coach change
- major offensive-line change
- team change
- rookie transition
- major role injury
- scheme change
- season boundary

The tracker emits a current-regime weight and historical-prior weight. Early in a new regime, historical priors retain authority. As the regime matures, current-regime evidence receives more weight.

This is an explicit mechanism for Weeks 1-4 and post-injury/post-QB-change uncertainty rather than pretending all trailing games are exchangeable.

## 4. Coherent Player State Graph

`PlayerStateGraph.simulate()` generates football outcomes first.

For a receiver or tight end:

```text
team dropbacks
    x route participation
        -> routes
routes
    x target rate implied by target share
        -> targets
targets
    x catch probability
        -> receptions
receptions
    x receiving efficiency
        -> receiving yards
```

Rushing opportunity is sampled from team rush volume and carry share. Touchdown opportunity is informed by red-zone and goal-line states.

For quarterbacks:

```text
team dropbacks
    -> sack / scramble / pass
    -> attempts
    -> completions
    -> passing yards / TD / INT
plus designed and scramble rushing
```

Each row is then passed through `fantasy.scoring.score_simulation_draws`, so custom league scoring remains authoritative.

The graph is a challenger. It does not silently overwrite the direct quantile bundle.

## 5. Uncertainty decomposition

`PlayerStateGraph.decompose_uncertainty()` uses matched Monte Carlo seeds and re-runs the graph while fixing one component at its expectation.

Reported components are:

- availability
- team volume
- role/opportunity
- execution
- environment
- residual model uncertainty

The variance-reduction shares are normalized for explanation. They are model sensitivity attribution, not causal decomposition.

## 6. Conditional calibration

`RecencyWeightedConditionalConformal` calibrates q10/q50/q90 using historical residuals only.

Features:

- recency weighting
- global fallback
- position groups
- target groups
- position x target groups
- sparse-group shrinkage
- explicit interval expansion
- median-bias correction

Always report interval coverage **and** interval width. Wider intervals are not a free win.

This module is the next experiment for the known pattern where some targets under-cover and others over-cover.

## 7. Forecast fusion

`HierarchicalForecastFusion` keeps forecast experts separate and visible.

Canonical experts are:

```text
DIRECT PLAYER MODEL
GENERATIVE FOOTBALL WORLD
EXTERNAL CONSENSUS / MARKET
```

Weights are convex and are learned only from archived historical predictions. The hierarchy is:

```text
global
  -> position
      -> position x target
          -> forecast horizon
              -> regime maturity bucket
```

Sparse contexts shrink toward parent weights. The output retains every expert forecast, selected fusion weights, and disagreement diagnostics.

`fusion_research_only=1` is emitted by default.

## 8. Insight Engine

`PlayerIntelligenceCard` standardizes decision-facing output:

- median and q10-q90
- P(top-12) and P(top-24), when league-wide correlated draws are supplied
- P(below replacement)
- P(active)
- expected routes, targets, carries, and red-zone opportunity
- role state
- role-change probability
- role maturity
- projection confidence
- main upside/downside driver
- consensus disagreement
- evidence freshness
- uncertainty decomposition

`projection_change_attribution()` explicitly labels its result as model attribution. It is not a causal explanation.

`scenario_summary()` and `PlayerStateForecastService.scenario()` support counterfactuals such as teammate active/inactive, altered availability, or changed environment assumptions.

`upside_path()` reports the sampled football conditions associated with crossing a user-supplied fantasy threshold.

## 9. Fantasy Season Simulator

`FantasySeasonSimulator` consumes weekly correlated player draws with shared `simulation_id` values.

For each path it:

1. solves legal weekly starter assignments;
2. evaluates scheduled head-to-head games;
3. applies optional league-median scoring;
4. builds standings using wins and points-for tiebreaks;
5. seeds the configured number of playoff teams;
6. advances a reseeded high-vs-low playoff bracket;
7. records the champion.

This produces manager-level:

- expected wins
- expected regular-season starter points
- playoff probability
- championship probability

`compare_roster_states()` evaluates a baseline and candidate roster state under the same season-simulation contract, enabling trade/waiver decisions in league outcomes instead of additive player values.

The current bracket is intentionally generic. Platform-specific playoff bracket rules should be normalized into the league snapshot before claiming exact platform parity.

## 10. Evidence tiers and experiment rigor

`EvidenceTier` is authoritative metadata, not decoration:

| Tier | Meaning |
|---:|---|
| 0 | synthetic only |
| 1 | single historical slice |
| 2 | multi-season isolated |
| 3 | multi-season downstream |
| 4 | live shadow season |
| 5 | decision-value validated |

`ExperimentEvidence.promotion_eligible` fails closed unless the experiment is preregistered, has at least Tier 2 evidence, passes negative controls, clears a minimum useful effect, and its paired confidence interval remains in the desired direction.

`paired_block_bootstrap()` defaults to season/week blocks so player-weeks from the same NFL week are not treated as independent observations.

`benjamini_hochberg()` provides an FDR control helper for experiment campaigns.

## Required research sequence

### P0: dynamic role and calibration

1. Build point-in-time route/snap/target/carry observations.
2. Compare `DynamicRoleFilter` against rolling-3/5/8 and existing structured role features.
3. Measure role-change lead time around injuries and depth-chart transitions.
4. Run recency-weighted conditional conformal on the frozen direct prediction archive.
5. Report coverage and sharpness by target, position, season, and early-season/post-change slice.

### P1: graph and fusion

1. Freeze direct predictions.
2. Generate Player State Graph challenger draws.
3. Compare direct vs graph on identical player-weeks.
4. Save every draw/quantile before aggregate metrics.
5. Run paired block bootstrap and negative controls.
6. Add the generative game-world expert.
7. Add consensus only as a separately auditable expert.
8. Learn fusion weights using archived folds only.
9. Inspect expert disagreement cohorts before any promotion decision.

### P1: fantasy decision replay

1. Reconstruct league snapshots point-in-time.
2. Produce correlated ROS weekly draws.
3. Replay legal lineups, waivers, and candidate trades.
4. Score lineup regret, playoff probability delta, championship probability delta, FAAB efficiency, and missed-candidate regret.
5. Preserve recommendation, available evidence, action taken, alternatives, and 1/3/6-week outcomes during the 2026 shadow season.

### P2+

Only after the graph and calibration gates are stable:

- decomposed execution heads
- tracking-data representation distillation
- richer objective context
- structured news role extraction

Broad personality inference and large sequence/transformer models remain low-authority research until simpler structure earns the need for them.

## Promotion boundary

Nothing in this package is production-promoted by implementation alone.

A challenger must still satisfy the repository's established discipline:

- point-in-time source coverage before predictive metrics
- frozen folds
- paired comparison to the strongest baseline
- season and position consistency
- calibration and sharpness
- shuffled-player and shifted-time controls where applicable
- downstream fantasy-decision evidence
- manual promotion

The intended end state is a probabilistic football state engine that can answer four questions at once:

1. What is the player likely to do?
2. Why is that distribution shaped this way or why did it change?
3. Which assumptions and uncertainties matter most?
4. What is the forecast worth in this exact fantasy league and roster state?
