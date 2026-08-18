# Game Intelligence v0.14: Possession Transition & Special Teams Laboratory

## Research objective

v0.13 separated continuing-drive pace and starting-field-position priors from the generic play-outcome sampler. That audit exposed the next structural seam: once a drive ends, the simulator still relies on fixed clock deductions, fixed next-possession starts, and a transparent field-goal heuristic.

v0.14 asks a narrower question:

> Given point-in-time history, can we model how possession actually transitions after punts, field goals, turnovers, touchdowns, and failed fourth downs well enough to improve downstream simulation without degrading team volume, player opportunity, or fantasy distributions?

The release is research-only. It does not change the production projection engine or the existing live research simulation endpoint.

## Why raw PBP is required

`build_play_intelligence_frame()` intentionally keeps offensive scrimmage plays. That is the correct contract for run/dropback, usage, outcome, and pace modeling, but it drops the special-teams rows needed to identify the actual terminal event of many possessions.

For example:

```text
3rd-down offensive play
        ↓
field-goal attempt
        ↓
kickoff / return
        ↓
next offensive scrimmage play
```

Using only scrimmage rows would attribute the transition to the third-down play. v0.14 instead builds a separate transition evidence frame from raw PBP and targets the first scrimmage play of the next offensive possession.

## Transition families

The first transparent taxonomy is:

- `TOUCHDOWN`
- `TURNOVER`
- `PUNT`
- `FIELD_GOAL_GOOD`
- `FIELD_GOAL_MISSED`
- `DOWNS`
- `HALFTIME`
- `OTHER`

This taxonomy is intentionally coarse. A later release may split interceptions from fumbles, kickoff touchbacks from returns, punt touchbacks from returns, or defensive touchdowns, but only if replay diagnostics show those distinctions matter.

## Targets

For every observed transition with a subsequent offensive possession, v0.14 derives:

1. `next_start_yardline_100`
2. `transition_seconds`

`transition_seconds` is measured from the terminal transition event to the next offensive scrimmage play. For punts and field goals, the terminal row is the punt/field-goal row itself rather than the preceding offensive scrimmage play.

## PossessionTransitionModel

The model is hierarchical and recency-weighted rather than a large black box.

Starting field position and transition timing shrink from contextual pools toward broader transition-type distributions. Context currently includes:

- transition type
- next offense
- source field zone
- recency

Sparse contexts cannot become authoritative merely because they exist. Their influence is controlled by an evidence-dependent shrinkage coefficient.

## Field-goal calibration

The same research layer includes a transparent empirical field-goal make model.

The baseline is a recency-weighted distance-bucket make rate. Team-specific evidence can move the probability away from that baseline only as evidence accumulates. The model does not yet use kicker identity, weather, roof, surface, holder/snapper state, or block environment.

Those are candidate v0.15+ evidence families, not silently assumed features.

## Negative controls

Two label-preserving controls are required.

### Transition target permutation

`next_start_yardline_100` and `transition_seconds` are permuted within transition-type × season groups.

This preserves:

- transition family counts
- season-level rule/environment effects
- the marginal target distribution within each transition family

while breaking the contextual mapping the model claims to exploit.

### Field-goal outcome permutation

Field-goal outcomes are permuted within distance-bucket × season groups.

This preserves the broad distance curve and season environment while breaking team-specific calibration signal.

## Full-simulation factorial

The v0.14 benchmark fixes learned play calling and state-conditioned opportunity allocation, then crosses two switches:

| Variant | Drive volume | Possession transitions |
|---|---|---|
| `legacy_drive_legacy_transition` | off | off |
| `drive_legacy_transition` | on | off |
| `legacy_drive_transition` | off | on |
| `drive_transition` | on | on |

The primary comparison is:

```text
drive_transition
        vs
drive_legacy_transition
```

This holds the v0.13 drive-volume mechanism constant and asks whether learned terminal transitions add downstream value.

## Full-simulation diagnostics

The probe records the prior team/player/fantasy metrics plus:

- punts
- field-goal attempts
- field goals made
- turnovers
- turnovers on downs
- starting field position
- drive count
- plays per drive
- continuing-drive seconds per play

The model must not be rewarded merely for improving an isolated field-position target while damaging scoring or fantasy calibration.

## Promotion gate

The v0.14 gate fails closed. By default it requires:

- at least three held-out seasons
- at least 200 games
- at least 500 isolated transition rows
- at least 100 field-goal attempts
- contextual start-field prediction beating transition-type baseline
- contextual start-field prediction beating the permutation control
- transition-time prediction beating type baseline and permutation
- field-goal log loss not worse than distance baseline or permutation
- meaningful full-simulation starting-field improvement
- no material regression in team play volume, drives, pace, points, special-teams counts, player opportunity, or fantasy pinball loss
- majority weekly starting-field wins

Passing the automated gate means only **eligible for manual research-champion review**.

It does not alter production projections.

## v0.15 evidence router

The benchmark routes the next release based on the observed bottleneck:

- isolated + downstream transition wins → latent drive strategy state
- isolated transition win but downstream loss → transition/action generation
- field-goal calibration weak → kicker/weather/field-goal model
- field position improves but scoring does not → decomposed scoring transitions
- team play volume still weak → drive termination/duration model
- ambiguous evidence → collect more replay evidence

This preserves the project rule: deeper architecture follows measured residual structure, not novelty.
