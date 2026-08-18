# v0.13 → v0.14 Evidence Router

Do not choose v0.14 before inspecting the full v0.13 historical artifact.

## Required first read

Compare:

```text
learned_state_legacy
learned_state_drive
```

across:

- team plays MAE;
- team drives MAE;
- plays per drive MAE;
- seconds per play MAE;
- starting field position MAE;
- team points MAE;
- player opportunity MAE;
- fantasy pinball loss and interval coverage;
- weekly win rates;
- season-specific stability.

Then inspect isolated pace evidence:

```text
state_pace_mae
team_base_pace_mae
permuted_state_pace_mae
```

## Pattern A — Drive volume improves broadly

If team plays, drives, and pace improve without downstream regression:

**Next:** persistent drive strategy state.

Start with a transparent Markov/state-space baseline before any sequence transformer.

Candidate states:

```text
SCRIPTED
NORMAL
HURRY_UP
COMEBACK
CLOCK_CONTROL
RED_ZONE_PACKAGE
```

Test whether state persistence improves:

- pace transitions;
- run/pass behavior;
- third/fourth-down aggression;
- red-zone conversion;
- fantasy covariance.

## Pattern B — Pace context wins directly, but simulated volume does not

This means the pace signal is real but is not enough to repair the state trajectory.

**Next:** drive-transition model.

Priority mechanisms:

1. first-down continuation probability;
2. drive termination type;
3. turnover field-position transfer;
4. punt/kickoff starting field position;
5. fourth-down continuation;
6. possession count;
7. drive duration.

Keep play outcome sampling unchanged while testing this layer.

## Pattern C — Volume improves, fantasy does not

**Next:** decomposed play outcomes.

The simulator is reaching a better quantity of opportunity but converting it incorrectly.

Prioritize:

```text
DROPBACK
  pressure -> sack
  target depth
  completion
  interception
  YAC
  touchdown conversion

RUSH
  stuffed probability
  conditional yards
  explosive probability
  fumble
  touchdown conversion
```

Retain correlated draws and benchmark each head independently.

## Pattern D — Starting field position is the only clear win

**Next:** special-teams and field-position transition model.

Potential point-in-time evidence:

- kickoff touchback rate;
- punt distance and return environment;
- turnover location;
- field-goal miss location;
- opponent special-teams tendencies.

Do not let special-teams complexity enter player projections until team scoring/volume replay improves.

## Pattern E — State pace loses to permuted context

Reject the state-conditioned pace feature family.

Investigate:

- clock-label construction;
- drive-boundary artifacts;
- team/coach regime changes;
- first-play-of-drive missingness;
- out-of-bounds and incomplete-pass clock behavior;
- no-huddle and timeout evidence;
- fourth-quarter score-state segmentation.

A negative-control failure is a model failure, not a tuning prompt.

## Pattern F — Wins only in stable regimes

Segment by point-in-time evidence maturity:

- same QB as prior week;
- same offensive play caller;
- stable top target shares;
- stable RB rotation;
- early season vs Weeks 5+;
- large injury/role transitions;
- favorite/underdog state;
- high/low totals.

If a model is only reliable under stable regimes, encode that authority explicitly rather than averaging the failure away.

## Pattern G — Drive volume and opportunity both work, uncertainty is weak

**Next:** covariance and calibration layer.

Evaluate whether simulated player distributions reproduce:

- QB/WR positive covariance;
- opposing-pass-game shootout covariance;
- RB/defense game-script relationships;
- target competition negative covariance;
- q10/q90 coverage by position and game environment.

Only after these transparent layers are competitive should a sequence encoder become a serious candidate.

## Long-range architecture

The intended progression is:

```text
player role state
+ team/coach state
+ drive volume
+ persistent drive strategy
+ defensive response
+ decomposed outcomes
        ↓
correlated play-by-play world model
        ↓
exact league scoring
        ↓
fantasy decisions
```

Every new layer must retain:

```text
point-in-time provenance
isolated benchmark
negative control
full downstream replay
manual promotion review
```
