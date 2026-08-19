# v0.15 Fourth-Down Decision & Drive-Termination Laboratory

v0.15 targets a structural gap that remains after the v0.14 possession-transition release: the simulator can model what happens **after** a possession ends, but its fourth-down `GO / PUNT / FIELD_GOAL` choice is still a hand-written heuristic.

The release keeps two claims separate:

1. **Action policy:** can historical state predict which fourth-down action an offense chooses?
2. **Termination hazard:** can historical state predict whether the current scrimmage play ends the drive?

Only the first claim receives experimental simulator authority in v0.15. The second remains diagnostic because a binary drive-end probability does not identify the terminal family that should be generated.

## Point-in-time evidence

`extract_fourth_down_decisions` works directly from raw play-by-play so punts and field goals remain visible. It emits one of:

- `GO`
- `PUNT`
- `FIELD_GOAL`

State includes only fields available at the decision:

- offense / opponent
- yards to go
- field position
- game clock
- score differential
- broad distance bucket
- broad field zone
- broad clock bucket
- score state

The model never uses the eventual outcome of the fourth-down decision as a feature.

`extract_drive_termination_events` separately labels whether each offensive scrimmage play is the final scrimmage play of its drive. It adds down, play family, field zone, distance, clock and score context. The target may use the completed historical drive because it is a supervised label, but the prediction inputs do not include future plays.

## FourthDownDecisionModel

The model is deliberately transparent and small.

It uses recency-weighted empirical probabilities with hierarchical shrinkage across:

1. global action frequency;
2. team base frequency;
3. global state-context frequency;
4. team × state-context frequency.

Sparse local evidence shrinks toward broader priors through `prior_strength` rather than being allowed to generate extreme probabilities.

The frozen v0.14 heuristic remains an explicit comparator. Its probability distribution is reconstructed analytically by `legacy_fourth_down_probabilities`, so isolated log loss and Brier score compare the learned model against the policy the simulator actually used.

## Negative control

Fourth-down actions are shuffled within:

`season × field_zone × distance_bucket`

This preserves broad football marginals while breaking finer team / clock / score mappings. A useful contextual model should beat this permuted challenger out of sample.

Termination labels are shuffled within:

`season × down_bucket × field_zone`

This preserves the strongest coarse termination structure while breaking finer state mapping.

## DriveTerminationHazardModel

The termination hazard estimates:

`P(drive ends after this scrimmage play | pre-play state)`

It uses the same recency-weighted hierarchical shrinkage philosophy as the action model.

In v0.15 it is **diagnostic-only**. The simulator records its probability and realized termination for calibration checks, but the hazard cannot terminate a possession by itself.

Why? Because forcing a drive to end requires another causal decision:

- touchdown?
- turnover?
- turnover on downs?
- end of half?
- another terminal family?

That terminal-family generation must be separately identified and benchmarked before receiving authority.

## Component-isolated simulation

`simulate_matchup_decision_probe` extends the v0.14 transition probe with a seventh RNG stream reserved for fourth-down policy.

The first six streams remain derived exactly as v0.14 derived them. When the learned policy is enabled, the frozen heuristic is still evaluated so its special-teams RNG consumption remains aligned. A field-goal uniform draw that the frozen heuristic would have consumed is also consumed even if the learned policy chooses another action.

This produces a strong parity contract:

> With the decision model disabled, v0.15 must reproduce the frozen v0.14 game, team and player core draws under the same seed.

The action challenger may change football trajectory through different decisions, but it does not get free stochastic divergence from unrelated special-teams randomness.

## Four-cell expanding replay

Drive volume is fixed on because v0.15 is testing policy against the current research world model. Possession-transition and fourth-down-decision authority are crossed:

| Variant | transition | learned decision |
|---|---:|---:|
| `legacy_transition_legacy_decision` | off | off |
| `legacy_transition_decision` | off | on |
| `transition_legacy_decision` | on | off |
| `transition_decision` | on | on |

The primary comparison is:

`transition_decision` vs `transition_legacy_decision`

Only fourth-down decision authority changes in that comparison.

Every test week is trained only on earlier chronology. Once a week has been evaluated, it may become history for later weeks.

## Isolated metrics

Fourth-down policy:

- multiclass log loss
- multiclass Brier score
- top-1 action accuracy
- frozen-heuristic log loss / Brier
- team-base log loss
- context-base log loss
- permuted-control log loss / Brier
- weekly win rate against the frozen heuristic

Termination hazard:

- binary log loss
- Brier score
- team-base log loss
- context-base log loss
- permuted-control log loss / Brier

## Downstream metrics

The four simulation cells retain all prior game-intelligence diagnostics and add:

- fourth-down decision count MAE
- fourth-down go-attempt MAE

Existing checks continue to cover:

- punts
- field-goal attempts and makes
- turnovers on downs
- drives
- plays per drive
- total plays
- pace
- starting field position
- team points
- player opportunity
- fantasy quantile / pinball metrics when actuals are supplied

## Promotion gate

`v015_decision_promotion_gate` fails closed unless there is enough multi-season evidence and the learned policy:

1. beats the frozen heuristic in isolated log loss;
2. beats the permutation control;
3. does not regress isolated Brier score;
4. improves simulated fourth-down go-attempt MAE by a minimum amount;
5. avoids material regression in decision count, punts, field goals, turnovers on downs, volume, scoring, opportunity and fantasy distributions;
6. wins often enough week by week rather than relying on a small pooled subset.

Passing this gate means only **eligible for manual research-champion review**.

It does not update production projections and does not alter the live simulation endpoint.

## What v0.15 does not claim

v0.15 does not establish that:

- fourth-down policy improves real historical fantasy accuracy;
- v0.14 possession transitions are promoted;
- the termination hazard should be used generatively;
- coaching identity, timeouts, kicker state, weather or market information are unnecessary;
- a deep sequence model is justified.

Those claims require the expanding historical benchmark.
