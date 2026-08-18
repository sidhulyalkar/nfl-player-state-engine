# v0.10 Game Intelligence & Play-by-Play Simulation

## Objective

v0.10 asks a different question from the player-level quantile engine:

> Given what was knowable before kickoff, what distributions of game scripts, play calls, team opportunity, player opportunity and fantasy outcomes are plausible?

The purpose is not to reconstruct a private playbook or claim access to a coach's internal mindset. It is to learn **observable strategic behavior** and how it changes with opponent, situation, personnel and game state.

The simulator is a research challenger. It cannot alter production weekly projections until frozen historical replay clears the promotion gate.

## Causal decomposition

```text
pregame environment
  spread / total / rest / venue / weather / roster state
            |
            v
team + play-caller state
  pace / neutral pass / early-down pass / RZ / third down
  shotgun / no-huddle / motion / PA / RPO / screens
            |
            v
opponent-conditioned play-call probability
  down + distance + field position + score + clock
            |
            v
conditional play outcome
  yards / first down / turnover / TD / clock runoff
            |
            v
next game state
            |
            v
player opportunity allocation
  dropbacks / targets / carries / red-zone shares
            |
            v
correlated raw player stat draws
            |
            v
exact LeagueConfig fantasy scoring
```

This decomposition makes errors diagnosable. A WR projection miss can be separated into errors in team volume, pass/run behavior, target concentration, conversion efficiency or touchdown variance.

## Point-in-time rule

Every historical prediction must be reproducible from evidence available before kickoff.

Allowed prediction-time inputs include:

- pre-snap state for the play being predicted;
- lagged/expanding offense and defense behavior;
- timestamped depth/snap/availability evidence available before the target game;
- pregame environment and market snapshots captured before kickoff;
- verified coaching/play-caller identity that was already known.

Forbidden inputs include:

- target-game play outcomes;
- target-game final stats;
- retrospective charting that was not actually available at prediction time;
- later injury/depth information;
- final-season aggregates used to predict earlier weeks.

## Team tendency state

`build_team_tendency_snapshots` builds shifted team-week state for:

- plays;
- overall, neutral, early-down, red-zone and third-down pass rate;
- shotgun and no-huddle rate;
- motion, play action, RPO and screen rate when available;
- seconds between plays;
- EPA per play;
- explosive-play rate;
- fourth-down scrimmage rate;
- defensive pass rate faced;
- defensive EPA/explosive/turnover/red-zone behavior faced.

The current matchup prior uses offense, defense faced and league context. This is intentionally transparent and should remain a challenger to more flexible hierarchical models.

## Coaching and play-caller evidence

Direct coach-vs-coach samples are sparse. v0.10 therefore treats them as a low-authority residual signal.

The direct matchup contribution:

- uses only prior meetings;
- grows with prior sample size;
- increases by 0.025 per prior game;
- is capped at 0.20 by default.

Future work should prefer hierarchical play-caller embeddings or partial pooling over raw head-to-head lookup tables.

Useful coaching evidence categories include:

- head coach and offensive/defensive play caller identity;
- play-caller continuity and coordinator changes;
- neutral pass over expectation;
- pace conditional on score state;
- early-down aggression;
- fourth-down aggressiveness;
- red-zone pass/run preference;
- motion/play-action/RPO/screen families;
- target/carry concentration;
- adaptation after halftime and after failed/successful concepts.

These are observable behaviors, not personality diagnoses.

## Player usage state

`build_player_usage_profiles` reconstructs point-in-time:

- carry share;
- target share;
- QB dropback share;
- red-zone carry share;
- red-zone target share;
- recency-weighted evidence volume.

The lookback crosses season boundaries correctly, which is essential for Week 1 priors.

Future role-state upgrades should add route participation, slot/outside alignment, personnel-specific participation, third-down role, goal-line role, pass protection, designed QB rush share and first-read/air-yard information where legitimate data is available.

## Play-call model

The first learned challenger is intentionally modest: regularized logistic regression for run vs dropback.

Features are restricted to:

- down and distance;
- field position;
- game clock and score differential;
- red-zone/goal-to-go/late-game state;
- point-in-time offense and opponent tendencies;
- pregame spread and total.

Formation/personnel observed on the target historical play are not fed to this initial play-call model because the simulator must first predict or generate those states before they can be used causally.

Later challengers may include:

1. hierarchical logistic/GAM models by team and play caller;
2. gradient boosting with calibrated probabilities;
3. recurrent/sequence state models using prior drives only;
4. latent offensive-concept and defensive-response states;
5. learned formation/personnel transition models;
6. drive-level or possession-level generative models.

Each must beat the transparent baseline out of sample.

## Conditional outcome model

The initial outcome model is an empirical hierarchical sampler conditioned on:

- play family;
- down;
- distance bucket;
- field-position bucket.

Sparse strata fall back to the play-family distribution. This is deliberately easy to audit. Later models can condition on offense/defense quality, formation, pressure, motion and player identities only after those states are available without leakage.

## Simulation state machine

The v0.10 simulator tracks:

- possession;
- score;
- game clock;
- down;
- distance;
- field position;
- run/dropback choice;
- fourth-down go/field-goal/punt choice;
- play result;
- turnover/touchdown state transitions;
- player target/carry/passer allocation.

Current research limitations are explicit:

- no overtime state machine;
- touchdown scoring uses seven points rather than a separate PAT/two-point model;
- fourth-down decisions start from transparent heuristics;
- player allocation begins with recency-weighted usage rather than a full personnel/route model.

These are benchmark targets, not hidden assumptions.

## Promotion gate

A simulator cannot promote from one favorable metric. By default it must have at least 100 historical games and demonstrate:

- better play-call log loss than the transparent matchup-profile baseline;
- no regression in team plays MAE;
- no regression in team pass-rate MAE;
- no regression in team points MAE;
- no regression in player opportunity MAE;
- no regression in fantasy pinball loss;
- q10-q90 fantasy coverage above the configured floor.

Missing required metrics fail closed.

Even when the gate returns `promoted=true`, the weekly automation does **not** automatically replace the production champion. Promotion remains an explicit reviewed action.

## Continual-learning loop

```text
completed games
    |
    v
refresh immutable evidence
    |
    v
rebuild next-week point-in-time states
    |
    v
fit candidate models to cutoff
    |
    v
replay recent frozen games
    |
    v
compare candidate vs transparent baseline + production projection
    |
    v
write metrics + data hashes + Git SHA + evidence tiers
    |
    v
research registry
```

The GitHub Action is an evidence producer, not an autonomous deployment agent.

## Highest-value next experiments after v0.10

1. Position/player opportunity heads conditioned on simulated game state.
2. Formation/personnel transition prediction using only genuinely point-in-time sources.
3. Defensive shell/pressure/box response modeling where licensed/current evidence exists.
4. Player-route and alignment state rather than target share alone.
5. Drive-level latent strategy states and halftime adaptation.
6. Team/play-caller partial pooling across coaching trees and scheme families.
7. Learned fourth-down and clock-management distributions.
8. Weather, OL continuity, travel/rest and officiating as low-dimensional context sensors.
9. Multi-model ensemble between direct player projections and game-generated player distributions.
10. Formal calibration of model-vs-market disagreement without forcing predictions toward betting lines.
