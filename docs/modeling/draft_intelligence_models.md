# Draft Intelligence Modeling Roadmap

## Goal

Build custom models that estimate **football outcomes first** and **draft decisions second**.

The system should not train one monolithic model to imitate expert rankings. It should learn several measurable objects and compose them into a league-aware decision:

```text
player outcome distribution
    -> league scoring distribution
    -> replacement / scarcity value
    -> roster marginal value
    -> draft-room timing
    -> pick recommendation
```

This decomposition is critical in 2QB leagues because generic one-QB ranks confound player quality with a completely different replacement economy.

## Modeling principle

Gemini is not the numerical prediction model. As of 2026, fine-tuning is not available through the Gemini API or Google AI Studio. The repository should train its football and draft models in Python, validate them with point-in-time backtests, expose deterministic results through the Product API, and use Gemini only for tool routing and explanation.

Current Google references:

- https://ai.google.dev/gemini-api/docs/model-tuning
- https://ai.google.dev/gemini-api/docs/function-calling
- https://ai.google.dev/gemini-api/docs/structured-output

## Model stack

### Model A: player availability and participation

Targets:

- probability active;
- snap share;
- route participation;
- dropback participation for QBs;
- expected games missed / availability distribution.

Useful inputs:

- prior-week official status;
- transactions and IR;
- depth chart;
- prior snap and route shares;
- age and recent workload;
- team role stability;
- timestamped news only after isolated validation.

Evaluation:

- log loss / Brier score;
- reliability diagrams;
- calibration by position;
- calibration conditional on injury designation.

### Model B: opportunity distribution

Position-specific targets:

QB:
- attempts;
- designed rushes;
- scramble volume;
- red-zone carries;
- team dropbacks.

RB:
- carries;
- targets;
- routes;
- goal-line opportunities.

WR / TE:
- routes;
- targets;
- air yards;
- red-zone targets.

Use quantile or distributional heads rather than one expected-value target. Position-specific models are preferred where the zero structure differs materially.

### Model C: conditional efficiency

Estimate production conditional on opportunity:

- completion rate and yards per attempt;
- catch probability;
- yards per carry;
- yards after catch / yards per reception;
- touchdown probability by opportunity type.

Keep volatile touchdown conversion strongly regularized. A model should not earn confidence by memorizing unsustainable touchdown rates.

### Model D: weekly and season fantasy distribution

Combine correlated component draws into weekly fantasy outcomes under the league's scoring rules.

Generate:

- q05 / q10 / q25 / q50 / q75 / q90 / q95;
- mean;
- variance;
- probability above useful position thresholds;
- expected games played;
- season distribution from weekly simulations.

The league scoring transformation happens after football-stat prediction. This allows one football model to support PPR, half-PPR, bonuses, TE premium, unusual passing scoring and other custom formats.

## 2QB-specific quarterback model

Quarterbacks require additional modeling because their fantasy value changes nonlinearly when 16 to 24+ of them must start every week.

Track separately:

- probability of retaining the starting NFL job;
- injury / benching risk;
- passing volume floor;
- rushing floor;
- red-zone rushing role;
- offensive line and pressure environment;
- receiver quality / continuity;
- coaching and scheme stability;
- backup competition;
- schedule-adjusted weekly floor.

A QB2 in a 2QB league should be valued partly for **starter security**. Losing an NFL starting job can turn a fantasy starter into a zero-replacement asset in a way that does not have a close analogue for most WR depth.

Recommended derived feature:

```text
qb_start_security
= P(active NFL starter in week t)
  integrated across fantasy regular season
```

Calibrate this separately from weekly fantasy points.

## Model E: league replacement and positional scarcity

This is deterministic given projections and league rules and should remain interpretable.

Inputs:

- team count;
- mandatory roster slots;
- FLEX and SUPER_FLEX eligibility;
- bench size;
- scoring rules;
- projected player distributions.

Outputs:

- starter allocation by position;
- replacement rank;
- replacement-point distribution;
- VORP;
- marginal value of the next player at each position;
- tier cliffs;
- scarcity curve.

For 2QB, compute the whole QB scarcity curve rather than one QB replacement point:

```text
QB1 -> QB8 -> QB12 -> QB16 -> QB20 -> QB24 -> QB28 -> QB32
```

The shape of that curve determines whether taking QB now is strategically urgent.

## Model F: draft pick survival / market hazard

Replace the current transparent normal-ADP approximation once enough historical draft data exists.

Prediction target:

```text
P(player is selected before pick k | player, platform, format, room state)
```

This is naturally a discrete-time survival / hazard problem.

Features:

- platform;
- league size;
- 1QB / 2QB / superflex;
- PPR setting;
- current pick;
- player consensus ADP;
- ADP dispersion;
- player position;
- recent positional run;
- roster needs of managers selecting before the user's next pick;
- time remaining to season start;
- draft-date recency.

Do not use final-season fantasy outcomes in this model. It predicts market behavior, not football quality.

Evaluation:

- Brier score for survival-to-next-pick;
- log loss;
- calibration by ADP bucket;
- calibration by league format;
- regret from `WAIT` recommendations where the player did not return.

## Model G: roster marginal-value simulator

This model/simulator answers the user's most important comparison question:

> What happens to my team if I take Player A rather than Player B?

For each candidate:

1. add the player to the current roster;
2. optimize legal weekly starters;
3. simulate injuries / availability;
4. simulate correlated weekly player outcomes;
5. calculate team weekly score distribution;
6. repeat for future schedule weeks;
7. compare with the pre-pick roster.

Outputs:

- marginal starter points;
- marginal q10 / q50 / q90 team points;
- probability candidate is a weekly starter;
- probability candidate is used in FLEX / SUPER_FLEX;
- depth value under an injury scenario;
- median-game win delta;
- playoff / championship probability delta when league schedule data is available.

This is preferable to hand-authored roster-construction heuristics once the simulation is validated.

## Model H: opponent-room model

Later, use live rosters of managers drafting before the user's next pick.

Estimate each manager's probability of selecting each position, not each exact player initially.

Example:

```text
P(next manager takes QB) = 0.72
P(next manager takes RB) = 0.11
...
```

Combine these hazards across the picks before the user's turn to improve player survival estimates.

Avoid modeling individual managers until there are enough repeat-draft observations to justify it. A small sample of a friend's drafts should not be presented as a learned personality.

## Data sources

### Football outcomes

Primary:

- nflverse weekly stats;
- schedules;
- play-by-play;
- rosters;
- depth charts;
- participation and snap counts where available;
- official injury / transaction evidence.

### Draft market

Maintain a separate timestamped market table containing:

- platform;
- league format;
- draft timestamp;
- overall pick;
- player ID;
- manager / roster ID where permitted;
- ADP snapshot timestamp;
- source.

Sleeper live and historical draft data is especially useful because the platform exposes read-only draft resources. Store raw snapshots immutably before deriving training rows.

### Consensus projections / ranks

These may enter only as separately identifiable market/model features with capture timestamps. They must not silently become ground truth.

## Validation protocol

### Time splits

Never randomly split player-week rows.

For player outcome models:

- train on earlier seasons/weeks;
- evaluate on later weeks / seasons;
- preserve real information cutoffs.

For draft-market models:

- train on drafts that occurred earlier in calendar time;
- evaluate on later drafts;
- include format-stratified reporting.

### Required baselines

Player models:

- rolling mean;
- exponentially weighted mean;
- position prior;
- market consensus where legally/timestamp-wise available.

Draft survival:

- current normal-ADP approximation;
- empirical ADP bucket frequency.

Roster value:

- current heuristic `roster_need_score`;
- VORP-only selection.

A complex model is promoted only if it beats the relevant simple baseline on frozen out-of-sample data.

## Draft-specific evaluation metrics

Do not judge the draft system only by season fantasy-point RMSE.

Track:

### Player prediction

- pinball loss by quantile;
- CRPS when full distributions are available;
- interval coverage;
- position calibration.

### Draft decisions

- value-over-next-best at time of pick;
- realized starter weeks;
- realized points above replacement;
- lineup regret;
- `WAIT` regret;
- positional scarcity regret;
- roster simulation calibration;
- season outcome delta versus transparent draft baselines.

### Strategy backtests

Replay historical drafts with only information available at each pick. Compare strategies such as:

- ADP-only;
- VORP-only;
- best projected points;
- zero-RB style heuristic;
- QB-priority heuristic;
- current live draft score;
- learned survival + roster simulator.

Run each strategy across multiple league formats. A strategy that wins in 12-team 2QB and loses in 8-team 2QB should not be summarized with one average score.

## Experiment registry

Every draft-model experiment should archive:

```text
experiment_id
Git SHA
training seasons / draft dates
feature cutoff rules
data hashes
league-format filters
targets
model class
hyperparameters
seed
calibration method
baseline metrics
candidate metrics
position / format metrics
promotion decision
```

Keep draft-survival models, player-outcome models and roster-simulation models independently versioned.

## Recommended implementation order

### v0.8A: live decision surface

- Product API live draft-board endpoint;
- candidate compare endpoint;
- React Draft War Room;
- multi-league switcher;
- exact live 2QB settings from Sleeper / ESPN;
- provenance / freshness UI.

No new learned model is required for this milestone.

### v0.8B: empirical draft market

- archive Sleeper draft histories;
- ingest timestamped ADP distributions;
- train/calibrate survival-to-next-pick model;
- benchmark against the normal-ADP approximation.

### v0.8C: roster simulator

- legal starter optimization on simulation draws;
- weekly team distributions;
- candidate marginal-value simulation;
- median-game scoring simulation.

### v0.9: stronger football state models

- component-level opportunity heads;
- explicit QB starter-security model;
- calibrated availability;
- improved touchdown / efficiency distributions;
- richer game-script correlation.

### Later

- sequence models;
- tracking representations;
- learned residual correlations;
- opponent-room positional hazard model;
- validated news / intelligence features.

## Non-negotiable boundary

The UI and Gemini should make the system easier to interrogate, not easier to hallucinate.

If a numerical field is not produced by a validated Python model or deterministic league calculation, the product should say it is unavailable rather than asking a language model to guess it.
