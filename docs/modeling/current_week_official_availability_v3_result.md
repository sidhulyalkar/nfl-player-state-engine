# Current-Week Official Availability v3 Result

## Decision

**Reject all three current-week official-availability formulations.**

The exploratory experiment completed successfully as an execution, but none of the registered formulations passed the predictive screen. No formulation is eligible for activation review, no production projection changes, and no activation setting changes.

This result does not revise or rescue the failed v2 persistent-claim experiment. It tests the narrower post-hoc hypothesis motivated by v2: whether resetting injury state to only the current game week before the 1.5-hour prediction cutoff produces useful incremental signal.

## Immutable run

- Workflow run: `32911904669`
- Scientific head: `04009344d1c2bec58ff13cf0596ff09956451862`
- Evidence artifact ID: `9587203663`
- Artifact digest: `sha256:c33ea0ee0c2f1b8978d17d91e9e1c78f2eaac9783bad269e9f93dac6624a63d3`
- Authority: `posthoc_exploratory_research_only`
- Automatic promotion: `false`
- Activation review eligibility: `false`
- Evaluation: REG, PPR, QB/RB/WR/TE, 2020-2024 source universe
- Registered prediction cutoff: 1.5 hours before kickoff
- Paired out-of-sample rows: **20,276**
- Scored seasons: **4**
- Season-week blocks: **64**

## Source observability

The source remained highly observable after the current-week reset semantics were applied.

- source rows: **28,882**
- source coverage: **99.747%**
- any current-week report prevalence: **17.419%**
- current-week practice prevalence: **17.340%**
- current-week game-designation prevalence: **4.546%**
- rows with latest eligible evidence after cutoff: **0**
- rows missing prediction cutoff: **0**

Source coverage therefore was not the reason the candidate formulations failed.

## Primary exploratory results

Effect is defined as `reference_mean_pinball - candidate_mean_pinball`, so positive values favor the candidate.

| Formulation | Baseline pinball | Candidate pinball | Effect | 95% block-bootstrap CI | P(improves) | p-value | joint FDR q | Screen |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `practice_current_week` | 1.389397 | 1.389509 | -0.000112 | [-0.001432, 0.001221] | 0.4215 | 0.578711 | 0.622689 | FAIL |
| `game_designation_current_week` | 1.389397 | 1.389632 | -0.000235 | [-0.001783, 0.001211] | 0.3775 | 0.622689 | 0.622689 | FAIL |
| `combined_current_week` | 1.389397 | 1.389402 | -0.000005 | [-0.001697, 0.001599] | 0.5145 | 0.485757 | 0.622689 | FAIL |

None of the confidence intervals has a positive lower bound. None of the jointly corrected q-values is near the registered `0.10` threshold. The combined formulation is numerically almost identical to baseline, not a credible win.

## Consistency

### Practice-only

- season consistency: **0.50**
- position consistency: **0.75**
- week consistency: **0.50**

### Game-designation-only

- season consistency: **0.75**
- position consistency: **0.50**
- week consistency: **0.50**

### Combined

- season consistency: **0.25**
- position consistency: **0.50**
- week consistency: **0.546875**

The registered minimum was `0.55` for season, position, and week consistency. No formulation cleared all three.

## Identity controls

All three formulations failed the shuffled-player identity negative control.

- practice identity-control effect: **+0.001134**, CI **[-0.000396, 0.002697]**
- game-designation identity-control effect: **+0.000042**, CI **[-0.001382, 0.001382]**
- combined identity-control effect: **-0.000286**, CI **[-0.001783, 0.001193]**

A legitimate player-specific availability feature should separate from its shuffled-identity control under the registered contract. These formulations did not.

## Leakage diagnostics

The deliberately future-shifted controls again show why the timestamp contract matters.

- practice shifted-time advantage: **+0.002034**, CI **[0.000258, 0.003689]**
- game-designation shifted-time advantage: **+0.001866**, CI **[0.000128, 0.003632]**
- combined shifted-time advantage: **+0.001704**, CI **[-0.000399, 0.003888]**

The first two future-shifted controls show a positive apparent advantage while the legitimate point-in-time formulations do not. This reinforces the no-hindsight boundary rather than creating evidence for activation.

## Registered blockers

### `practice_current_week`

1. `incremental_effect_not_credibly_positive`
2. `joint_exploratory_fdr_q_above_0_10`
3. `inconsistent_season_effect`
4. `inconsistent_week_effect`
5. `identity_negative_control_failed`

### `game_designation_current_week`

1. `incremental_effect_not_credibly_positive`
2. `joint_exploratory_fdr_q_above_0_10`
3. `inconsistent_position_effect`
4. `inconsistent_week_effect`
5. `identity_negative_control_failed`

### `combined_current_week`

1. `incremental_effect_not_credibly_positive`
2. `joint_exploratory_fdr_q_above_0_10`
3. `inconsistent_season_effect`
4. `inconsistent_position_effect`
5. `inconsistent_week_effect`
6. `identity_negative_control_failed`

All formulations additionally retain the activation-review blocker:

`posthoc_formulation_requires_independent_confirmation`

Even a successful exploratory screen would not have been sufficient for production activation.

## Interpretation

The v2 failure was not explained away by stale claim persistence alone.

Resetting the structured injury state to the current game week fixes the specific stale-lifecycle defect diagnosed after v2, but the repaired formulations still fail to add credible incremental predictive information over the frozen numerical baseline under this feature representation.

The correct conclusion is therefore narrower and stronger:

> **Do not activate official availability as a generic residual feature in the current player quantile model.**

Official availability can still be operationally important for hard player-status handling, but that is a different modeling question from whether these soft numerical features improve the baseline forecast distribution.

## Next step

PR #31 provides a separate prospective 2026 collection lane. That collector should remain evidence infrastructure, not an excuse to keep refitting the failed v3 hypotheses on the same 2020-2024 universe.

Future availability work should require a materially different, preregistered hypothesis such as explicit participation/active-state modeling or hard game-status gating, followed by prospective confirmation. Repeated feature engineering around these same three failed formulations would be post-selection rather than confirmation.
