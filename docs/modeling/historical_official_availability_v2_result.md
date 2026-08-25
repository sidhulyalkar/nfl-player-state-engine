# Historical Official Availability v2 Result

## Decision

**Reject the current combined structured official-availability formulation.**

The registered regular-season experiment completed successfully as an execution, but the candidate failed the predictive evidence gate and is not eligible for activation review. No production projection or activation setting changed.

Machine-readable evidence lives at `experiments/historical_official_availability_v2/primary_result.json`.

## Immutable run

- Workflow run: `32882130064`
- Scientific head: `19f03373358eaaf0dd4c2976c5649e5839801662`
- Evidence artifact ID: `9577839705`
- Artifact ZIP SHA-256: `73f1c1dd43901cca7c877f485fbd84b6d8fc22e7e212ea4aaacda416b8fee2e9`
- Numerical baseline identity: `a036c410e0bb1ec670e3fa0f7d6e14e1433322b6eeabdaa81c25c8daee43a29c`
- Canonical injury archive identity: `c150ff3f78eb48e90e9c907640af855dd15b8f98564dc214ca0e9b61a541cff1`
- Evaluation: REG, PPR, QB/RB/WR/TE, 2020-2024 source universe
- Registered prediction cutoff: 1.5 hours before kickoff

## Source observability

The evidence source itself was not the limiting factor.

- REG player-week source rows: **28,882**
- official/injury source coverage: **99.75%**
- raw current-week injury evidence prevalence: **17.43%**
- missing position rows: **0**

Every season-position slice had approximately 99.5% to 100% source coverage.

## Primary paired result

The walk-forward benchmark produced **20,276 paired out-of-sample player-weeks**, spanning four scored seasons and 64 season-week blocks after the minimum training window.

| Metric | Numerical baseline | + official availability |
| --- | ---: | ---: |
| Mean q10/q50/q90 pinball | 1.391012 | 1.395190 |
| q50 MAE | 4.354269 | 4.356646 |
| q10-q90 empirical coverage | 0.810219 | 0.821908 |

Primary effect is defined as `reference_loss - candidate_loss`, so positive values favor the candidate.

- effect: **-0.0041779**
- relative pinball regression: approximately **0.30% worse**
- 95% season-week bootstrap CI: **[-0.0071021, -0.0015203]**
- probability the candidate improves: **0.001**
- p-value: **0.9990005**
- Benjamini-Hochberg FDR q-value: **1.0**

The entire confidence interval is below zero. This is a negative result, not an underpowered near miss.

## Consistency

The candidate was unfavorable in every evaluated season and all four supported positions.

Season effects, reference minus candidate:

- 2021: `-0.003579`
- 2022: `-0.005098`
- 2023: `-0.001826`
- 2024: `-0.005923`

Position effects:

- QB: `-0.011955`
- RB: `-0.005454`
- TE: `-0.002406`
- WR: `-0.002162`

Registered consistency metrics therefore failed:

- season consistency: **0.0**
- position consistency: **0.0**
- week consistency: **0.421875**, below the 0.55 gate

## Controls and calibration

The interval-calibration limits themselves were not the failure:

- overall coverage-gap regression: `0.011689`, below the 0.02 maximum
- worst supported-position coverage-gap regression: `0.015194`, below the 0.05 maximum

The identity control did fail:

- real candidate vs shuffled identity-control effect: `-0.0035056`
- 95% CI: `[-0.0062544, -0.0009729]`
- identity negative control passed: **false**

The deliberately future-shifted leakage diagnostic produced a positive apparent advantage:

- shifted-time advantage: `+0.0053628`
- 95% CI: `[0.0026145, 0.0081426]`

This is useful as a sanity check: future availability information can improve apparent performance, while the legitimate point-in-time formulation did not.

## Registered blockers

The final model and activation gates both contain:

1. `incremental_effect_not_positive`
2. `incremental_effect_ci_not_positive`
3. `fdr_q_above_threshold_or_missing`
4. `inconsistent_season_effect`
5. `inconsistent_position_effect`
6. `inconsistent_week_effect`
7. `identity_negative_control_failed`

`eligible_for_activation_review = false`.

## Post-hoc diagnosis, not confirmatory evidence

After freezing the negative result, we inspected the feature lifecycle to understand why a highly observable source harmed forecasts.

The raw source contains current-week player evidence on only **17.43%** of player-weeks, but the generic structured ledger reports a prior official snapshot on **81.29%** of evaluated rows. Its contradiction rate is **53.77%**.

The reason is architectural. Official practice/game claims have short exponential half-lives, but unsuperseded claims remain active indefinitely in `effective_claims_as_of()`. Decay reduces their weight, but snapshot presence and cumulative claim counts persist. In the completed artifact:

- median age of the latest active official claim: approximately **43.8 days**
- 75th percentile age: approximately **319 days**

This strongly suggests that a weekly injury report should not be represented as an everlasting generic claim stream. A source-covered absence on a later report should be able to reset stale injury state.

These observations are **post-hoc diagnostics**. They do not alter, rescue, or reclassify the failed primary experiment.

## Follow-up experiments

The next availability formulation must be a new experiment identity because its hypothesis was informed by this result.

1. **Current-week state semantics.** Construct official availability directly from the latest source row before that game cutoff. When a team's report source is covered and a player is absent, reset the weekly injury state rather than carrying old claims forward indefinitely.
2. **Practice vs game designation decomposition.** Test current-week practice participation and game designation separately before combining them.
3. **Pregame-context sensitivity.** Repeat the frozen experiment after excluding `spread_line`, `total_line`, `roof`, `temp`, and `wind`, whose exact historical availability at the 1.5-hour cutoff is not established by the final nflverse games table. This is already running as a separate sensitivity analysis and cannot make the failed primary formulation activation-eligible.
4. **Prospective confirmation.** Any new formulation discovered using these 2020-2024 results should require an untouched/prospective shadow-season confirmation before production authority.

A separate finding also deserves its own study: the objective-opportunity staircase variant passed the model-quality gate, but source coverage for that family was not measured. That signal should be qualified independently rather than being attributed to injury intelligence.
