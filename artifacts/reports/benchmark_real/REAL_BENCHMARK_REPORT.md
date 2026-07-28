# Real nflverse benchmark: 2020–2025

**Protocol:** 2020 regular season is the warm-up; 2021–2025 are expanding-window out-of-sample seasons. Models retrain at each season boundary. Quantile engine uses q10/q50/q90 HistGradientBoosting models with an explicit pregame feature allowlist.

## Engine versus strongest baseline

| target             | best_baseline   |   engine_mae |   baseline_mae |   mae_improvement_pct |   engine_mean_pinball |   baseline_mean_pinball |   pinball_improvement_pct |   engine_coverage |   coverage_error_abs | verdict   |
|:-------------------|:----------------|-------------:|---------------:|----------------------:|----------------------:|------------------------:|--------------------------:|------------------:|---------------------:|:----------|
| carries            | rolling_5       |       3.1442 |         1.5783 |              -99.2119 |                0.7844 |                  0.5157 |                  -52.1068 |            0.9200 |               0.1200 | loss      |
| fantasy_points_ppr | rolling_5       |       4.3941 |         4.6175 |                4.8382 |                1.3992 |                  1.4846 |                    5.7560 |            0.8182 |               0.0182 | win       |
| passing_yards      | rolling_5       |      65.9944 |        70.9776 |                7.0208 |               20.7321 |                 22.2285 |                    6.7318 |            0.7173 |               0.0827 | win       |
| receiving_yards    | rolling_5       |      15.9417 |        16.9130 |                5.7430 |                5.1094 |                  5.4786 |                    6.7383 |            0.8525 |               0.0525 | win       |
| receptions         | rolling_5       |       1.2673 |         1.3132 |                3.4963 |                0.4042 |                  0.4185 |                    3.4163 |            0.9057 |               0.1057 | win       |
| rushing_yards      | rolling_5       |       8.5369 |         9.2476 |                7.6845 |                2.8579 |                  3.1263 |                    8.5846 |            0.8494 |               0.0494 | win       |
| targets            | rolling_5       |       1.6146 |         1.6719 |                3.4283 |                0.5298 |                  0.5350 |                    0.9737 |            0.9017 |               0.1017 | win       |

## Main findings

- The quantile engine wins 6 of 7 targets by mean pinball loss.
- Carries is a decisive pooled-model failure: zero-heavy WR rows collapse RB/QB medians. A completed position-specific correction reduces mean pinball to 0.5091 versus 0.5157 for rolling-5 and is integrated into the v0.3 production bundle.
- Targets and receptions are the cleanest engine wins and the most natural first-stage opportunity variables.
- Fantasy, passing yards, receiving yards, and rushing yards improve, but lower-tail/upper-tail calibration remains position dependent.
- Intelligence features should first influence availability, participation, routes, targets, and carries. They should not be injected directly into yardage or fantasy heads until opportunity models are stable.

## Season stability

| target             |   winning_seasons |   evaluated_seasons |
|:-------------------|------------------:|--------------------:|
| carries            |                 0 |                   5 |
| fantasy_points_ppr |                 5 |                   5 |
| passing_yards      |                 4 |                   5 |
| receiving_yards    |                 5 |                   5 |
| receptions         |                 5 |                   5 |
| rushing_yards      |                 5 |                   5 |
| targets            |                 5 |                   5 |

## Position stability

| target             | position   |   engine_mean_pinball | best_baseline   |   baseline_mean_pinball |   improvement_pct | engine_wins   |
|:-------------------|:-----------|----------------------:|:----------------|------------------------:|------------------:|:--------------|
| carries            | QB         |                 0.852 | rolling_5       |                   0.593 |           -43.620 | False         |
| carries            | RB         |                 1.885 | rolling_5       |                   1.160 |           -62.506 | False         |
| carries            | WR         |                 0.077 | position_prior  |                   0.079 |             2.834 | True          |
| fantasy_points_ppr | QB         |                 1.908 | rolling_5       |                   1.998 |             4.521 | True          |
| fantasy_points_ppr | RB         |                 1.417 | rolling_5       |                   1.505 |             5.861 | True          |
| fantasy_points_ppr | TE         |                 1.103 | rolling_5       |                   1.179 |             6.383 | True          |
| fantasy_points_ppr | WR         |                 1.399 | rolling_5       |                   1.487 |             5.886 | True          |
| passing_yards      | QB         |                20.732 | rolling_5       |                  22.228 |             6.732 | True          |
| receiving_yards    | RB         |                 3.202 | rolling_5       |                   3.509 |             8.761 | True          |
| receiving_yards    | TE         |                 4.617 | rolling_5       |                   4.992 |             7.509 | True          |
| receiving_yards    | WR         |                 6.549 | rolling_5       |                   6.954 |             5.823 | True          |
| receptions         | RB         |                 0.346 | rolling_5       |                   0.365 |             5.234 | True          |
| receptions         | TE         |                 0.386 | rolling_5       |                   0.404 |             4.273 | True          |
| receptions         | WR         |                 0.450 | rolling_5       |                   0.460 |             2.139 | True          |
| rushing_yards      | QB         |                 3.609 | rolling_5       |                   3.909 |             7.674 | True          |
| rushing_yards      | RB         |                 6.237 | rolling_5       |                   6.643 |             6.110 | True          |
| rushing_yards      | WR         |                 0.540 | position_prior  |                   0.586 |             7.811 | True          |
| targets            | RB         |                 0.415 | rolling_5       |                   0.430 |             3.590 | True          |
| targets            | TE         |                 0.487 | rolling_5       |                   0.496 |             1.697 | True          |
| targets            | WR         |                 0.623 | rolling_5       |                   0.620 |            -0.452 | False         |

## Activation order

1. Validate the integrated position-specific carries heads on future timestamped weeks; explore hurdle/count variants only if they improve further.
2. Calibrate q10/q90 by target and position using out-of-fold conformal adjustments.
3. Add official injury/practice/depth-chart features to participation and opportunity heads.
4. Add snap counts, route participation, team personnel and red-zone role features.
5. Evaluate public-context/persona features only as timestamped residual modifiers in an isolated ablation.
6. Promote an intelligence feature only when it improves multiple held-out seasons without degrading calibration or subgroup stability.