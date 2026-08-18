# Game Intelligence v0.13 — Drive Volume & State Laboratory

v0.13 tests a narrower hypothesis than a new sequence architecture:

> Does separating pace and drive-start field position from the generic play-outcome sampler improve the simulated distribution of NFL game volume?

The release is research-only. The established v0.12 simulation path remains the live research API path until historical replay earns a change.

## Why this layer exists

v0.12 can distinguish play-calling and player-allocation errors, but the simulator still mixes several mechanisms:

```text
play outcome sample
    ├── yards / first down / turnover / touchdown
    └── seconds between plays

possession reset
    └── fixed starting field position
```

That makes it difficult to know whether a team-volume miss comes from football efficiency, pace, or unrealistic possession starts.

v0.13 extracts two mechanisms into an independent challenger:

```text
DRIVE VOLUME MODEL
    ├── state-conditioned clock runoff
    └── point-in-time drive starting field position
```

Everything else remains separately switchable.

## DriveVolumeModel

`src/player_state_engine/game_intelligence/drive.py`

The model is hierarchical and empirical rather than a black-box regressor.

### Pace context

Clock runoff is conditioned on:

- score state: trailing / neutral / leading;
- late-game state;
- play family: rush / dropback;
- red-zone state.

Every contextual distribution is shrunk toward the offense's recent base pace using recency-weighted evidence. Sparse context therefore falls back toward team history rather than producing extreme estimates.

The current default half-life is six weeks and the default context prior strength is 24 effective observations.

### Drive starts

Drive starting field position is sampled from a transparent mixture:

```text
60% offense recent drive starts
30% opponent drive starts allowed
10% league drive starts
```

This is intentionally simple. It exists to test whether replacing the fixed 75-yardline reset has measurable value before special-teams or possession-transition modeling is added.

Drive starts are derived from scrimmage-play drive boundaries. They are therefore a useful field-position proxy, not a complete special-teams model.

## Independent RNG streams

`drive_simulator.py` separates stochastic components into independent streams:

```text
special teams / fourth down
play call
play outcome
player allocation
drive tempo
```

This matters for A/B replay. Enabling an allocator or pace model should not change the next play's outcome merely because it consumed one extra random number.

The streams are deterministic for a fixed seed and simulation index.

## Eight-cell replay

v0.13 crosses three binary model switches:

```text
PLAY CALL      profile / learned
ALLOCATION     static / state-conditioned
DRIVE VOLUME   legacy / learned
```

This creates eight cells:

```text
profile_static_legacy
learned_static_legacy
profile_state_legacy
learned_state_legacy
profile_static_drive
learned_static_drive
profile_state_drive
learned_state_drive
```

The primary drive comparison is:

```text
learned_state_drive
        vs
learned_state_legacy
```

so pace and drive-start mechanics are evaluated while the stronger v0.12 play-call and opportunity challengers are held constant.

## Drive diagnostics

Every v0.13 simulation tracks:

- drives per team;
- plays per drive;
- seconds per play;
- mean offensive `yardline_100` at drive start;
- total plays;
- pass rate;
- points;
- player carries and targets;
- player fantasy distributions.

Historical replay reports MAE for:

```text
team plays
team drives
plays per drive
seconds per play
starting field position
team points
player opportunity
fantasy median / pinball / coverage
```

This keeps volume improvements from hiding scoring or fantasy regressions.

## Pace negative control

The isolated pace test permutes `seconds_between_plays` within each team-season.

This preserves:

- the team;
- season;
- number of plays;
- marginal pace distribution.

It breaks the mapping between play state and pace.

For pace context to earn authority:

```text
real state-conditioned pace
    < team-only pace error
AND
real state-conditioned pace
    < permuted-state pace error
```

A model that cannot beat this control should be rejected or redesigned rather than deepened.

## Promotion gate

`v013_drive_volume_promotion_gate` can only recommend promotion into the **research simulator champion**.

Default evidence includes:

- at least three held-out seasons;
- at least 200 replayed games;
- measurable team-play MAE improvement;
- team pace improvement;
- no material regression in drives, plays/drive, start field position, points, player opportunity, or fantasy pinball loss;
- majority weekly team-volume wins;
- state pace beating both team-only and permuted controls.

Missing metrics fail closed.

Even a cleared gate does not change production projections automatically.

## Historical workflow

Use:

```text
.github/workflows/v013_drive_volume_benchmark.yml
```

The workflow has two modes.

### Smoke

The default mode intentionally uses a small 2025 window, three simulations per game, and two games per week. It validates acquisition, model fitting, simulation, reporting, and artifact upload without burning a large Actions budget.

### Full

Full mode uses the requested seasons/weeks and defaults to the 2023-2025 held-out window with 2021-2022 warm-up history.

Artifacts include:

- `weekly_drive_factorial_metrics.parquet`;
- `weekly_pace_negative_control.parquet`;
- `summary.json`;
- `report.md`;
- acquisition manifest.

The Markdown report is also appended to the GitHub Actions job summary.

## v0.14 routing

The benchmark emits a conservative recommendation rather than assuming the next architecture.

### Volume and fantasy improve

Next experiment: persistent latent drive strategy state.

Candidate interpretable states:

```text
SCRIPTED
NORMAL
HURRY_UP
COMEBACK
CLOCK_CONTROL
RED_ZONE_PACKAGE
```

### Pace signal is real but full-game volume does not improve

Next experiment: drive continuation, possession termination, special-teams starts, and field-position transitions.

### Volume improves but fantasy does not

Next experiment: decomposed play outcomes such as completion, yards, turnovers, and touchdown conversion.

### Pace cannot beat the negative control

Reject or redesign drive context before adding complexity.

## Claim boundary

v0.13 does **not** claim the drive-volume model improves NFL or fantasy accuracy.

The release implements the experiment required to test that claim while keeping the existing simulation and production projection paths unchanged.
