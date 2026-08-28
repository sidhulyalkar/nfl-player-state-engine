# Current-week official availability v3

## Status

**Post-hoc exploratory research only.** This experiment was designed after the registered v2 official-availability formulation failed. It can identify a candidate for independent confirmation, but it cannot make any feature eligible for activation review and cannot modify production projections.

## Why v3 exists

The v2 REG experiment had excellent source coverage but a clearly unfavorable predictive effect. The generic structured ledger also showed a large gap between current-week injury-report prevalence and the prevalence of an active official snapshot. Post-hoc inspection found that unsuperseded claims can remain active for many weeks while their weights decay.

The separate pregame-context sensitivity removed `spread_line`, `total_line`, `roof`, `temp`, and `wind`. That reduced the magnitude of the v2 penalty but did not make the effect positive or pass the identity, FDR, consistency, or activation gates. The follow-up therefore targets the state representation itself rather than tuning the failed persistent representation.

## Question

Does **only the official state observable for the current game week before the prediction cutoff** add useful out-of-sample information beyond the numerical model?

The experiment decomposes this into three registered exploratory formulations:

1. `practice_current_week`
2. `game_designation_current_week`
3. `combined_current_week`

The three p-values are corrected jointly with Benjamini-Hochberg. No formulation may be selected first and then evaluated as though it had been the only hypothesis.

## Frozen source boundary

v3 reuses the fully content-addressed v2 source universe:

- numerical baseline identity: `a036c410e0bb1ec670e3fa0f7d6e14e1433322b6eeabdaa81c25c8daee43a29c`
- injury archive identity: `c150ff3f78eb48e90e9c907640af855dd15b8f98564dc214ca0e9b61a541cff1`
- schedule commit: `67fa4d790ba09e5f0e2868b49ef9dbbd8946bb22`
- model config SHA-256: `fcec5d12b061c7cdf413d159f9486af2b19823b973f6fac4db5f56d2d3435b85`
- seasons: 2020-2024
- evaluation season type: `REG`
- target: `fantasy_points_ppr`
- prediction cutoff: 1.5 hours before kickoff

The registered wrapper reuses the v2 raw-file verification contract and independently checks the canonical injury archive identity before fitting.

## Current-week semantics

The candidate does **not** use the persistent structured claim ledger.

For each player-game row, the source adapter selects only an injury row from the same `season`, `week`, team, and player whose `date_modified` is at or before that game's prediction cutoff.

If the team's current-week injury source is observable but the player has no qualifying row:

- current-week practice score remains null;
- current-week game-designation score remains null;
- explicit `found` flags are zero;
- no prior-week injury claim is carried forward;
- absence from the report is **not hard-coded as full practice or healthy**.

This allows the model to distinguish source-covered report absence from an observed practice or game designation without inventing a clinical state.

## Formulations

### Practice current week

Features:

- `cw_practice_score`
- `cw_practice_is_limited`
- `cw_practice_is_dnp`
- `cw_practice_found`

Long-form nflverse values such as `Limited Participation in Practice` and `Did Not Participate in Practice` are canonicalized by the permanent historical adapter.

### Game designation current week

Features:

- `cw_game_score`
- `cw_game_is_questionable`
- `cw_game_is_doubtful`
- `cw_game_is_out`
- `cw_game_found`

### Combined current week

Uses both feature groups plus `cw_any_report_found`.

## Numerical reference

The numerical feature model is built from the same frozen raw player-week source with the normal strictly lagged/history feature engine. The following final-game context fields are excluded from **all** v3 variants because the frozen schedules table does not establish their exact value at the 1.5-hour historical cutoff:

- `spread_line`
- `total_line`
- `roof`
- `temp`
- `wind`

The treatment columns use the `cw_` namespace and are added explicitly. They cannot enter the numerical baseline through generic `availability_` family discovery.

## Fixed exploratory screen

The Git-tracked registry fixes the following before the v3 fit:

| Gate | Value |
| --- | ---: |
| Block bootstrap samples | 2,000 |
| Random seed | 4203 |
| Minimum source coverage | 0.80 |
| Joint BH FDR q | <= 0.10 |
| Minimum season consistency | 0.55 |
| Minimum position consistency | 0.55 |
| Minimum week consistency | 0.55 |
| Minimum paired rows | 250 |
| Minimum paired seasons | 2 |
| Minimum season-week blocks | 8 |
| Minimum rows for a supported position slice | 50 |
| Maximum overall 80% coverage-gap regression | 0.02 |
| Maximum supported-position coverage-gap regression | 0.05 |

The incremental effect is `reference_loss - candidate_loss`; positive favors the current-week candidate. The effect and its lower 95% blocked-bootstrap confidence bound must both be positive.

## Negative controls

### Identity shuffle

Only the current-week treatment columns are shuffled within season/week/position strata. The real candidate must beat this shuffled version with a positive bootstrap interval.

### Shifted-time leakage sensitivity

The next same-season player current-week state is intentionally moved backward. This estimates how much apparent signal becomes available if future information leaks into an earlier prediction row. It is diagnostic only.

## Calibration

The experiment records q50 MAE, empirical q10-q90 coverage, overall coverage-gap regression, and the worst supported-position coverage-gap regression. A raw accuracy improvement that materially damages uncertainty calibration fails the exploratory screen.

## Authority boundary

A v3 formulation can have `registered_exploratory_screen_passed = true`, but **every v3 formulation always has**:

- `authority = posthoc_exploratory_research_only`
- `automatic_promotion = false`
- `eligible_for_activation_review = false`

Any apparent winner was conceived using information learned from the 2020-2024 v2 result. It therefore requires an independent untouched or prospective confirmation dataset/season before manual activation review is even possible.

## Reproduction

The authoritative operator is:

```bash
python scripts/run_registered_current_week_official_availability_v3.py \
  --numerical-root data/raw/historical_numerical_baseline_v2 \
  --injury-root data/raw/historical_injury_archive_v2 \
  --output-dir artifacts/intelligence_ablations/current_week_official_v3
```

Only source/output locations are configurable. Seed, bootstrap count, formulations, evaluation seasons, target, cutoff, source identities, model config, removed context, and statistical gates come from `experiments/current_week_official_availability_v3/registered_inputs.json` and are checked before fitting.
