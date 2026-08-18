# v0.14 Experiment Queue and v0.15 Router

The next architectural step must be chosen from frozen replay evidence rather than model novelty.

## P0 — Run the full v0.14 expanding replay

Default evidence window:

- acquire 2021–2025 history
- hold out 2023, 2024, and 2025
- Weeks 1–18
- smoke first, then all games
- begin with 15 simulations per game/variant and increase only if Monte Carlo noise obscures comparisons

Inspect both pooled metrics and weekly win rates. A pooled improvement driven by a handful of weeks is not sufficient.

## P1 — Latent drive strategy state

Choose this only if learned possession transitions improve isolated targets **and** improve or preserve downstream field position, scoring, opportunity, and fantasy distributions.

Start with a transparent persistent state model before any transformer:

- SCRIPTED
- NORMAL
- HURRY_UP
- COMEBACK
- CLOCK_CONTROL
- RED_ZONE_PACKAGE

Candidate first implementation: a small Markov or HMM-style state model with point-in-time coach/team priors and explicit transition probabilities.

Required test: persistent state must improve future within-drive play/pace/outcome likelihood beyond the current observable state features.

## P2 — Transition-action generation

Choose this if next-possession field position is predictable **conditional on terminal event type**, but the full simulator does not improve.

That pattern means the simulator may be generating the wrong number or location of punts, field goals, turnovers on downs, or other possession endings.

Candidate work:

- probabilistic fourth-down action model
- punt versus field-goal versus go decision calibration
- drive termination hazard
- game-state and coach-specific fourth-down behavior
- score/time/field-position interaction

Keep action generation separate from transition outcome quality.

## P3 — Kicker, weather, and field-goal state

Choose this when the empirical field-goal layer does not beat the distance baseline or permutation control.

Candidate point-in-time evidence:

- kicker identity and recent attempt history
- distance-specific kicker shrinkage
- stadium / roof state
- wind and temperature forecast available before kickoff
- surface
- long-snapper / holder continuity when available
- block environment

Weather must use archived prediction-time forecasts or another timestamp-safe representation, not final observed game weather masquerading as pregame information.

## P4 — Decomposed scoring transitions

Choose this if starting field position improves but team points or fantasy distributions do not.

Candidate heads:

- red-zone entry → touchdown / field goal / turnover
- completion and air-yards depth
- YAC
- pressure / sack
- turnover probability
- rushing efficiency
- touchdown conversion

The current empirical play-outcome sampler remains the baseline.

## P5 — Drive termination and duration

Choose this when field-position transitions look reasonable but team play volume remains weak.

Model the chain explicitly:

```text
pregame pace
→ drive continuation
→ drive termination
→ possession transition
→ drive count
→ plays per drive
→ team plays
```

Candidate diagnostics:

- drive survival curve by play count
- first-down conversion hazard
- third/fourth-down termination
- turnover hazard
- score-state duration
- possession-duration calibration

## P6 — Richer special-teams evidence

Only pursue this if transition residuals concentrate in special-teams families.

Candidate evidence:

- punter identity
- returner identity
- touchback rate
- punt distance / hang-time proxies
- kickoff touchback rate
- return-yard distributions
- blocked-kick tendencies
- stadium and weather

Player-level return modeling should remain separate from offensive player-state projections until its downstream value is demonstrated.

## P7 — Regime segmentation

If the challenger wins only under stable coaching/QB/role conditions, model evidence maturity explicitly rather than averaging incompatible regimes.

Potential regime boundaries:

- coaching/play-caller change
- QB starter change
- major OL continuity break
- role overhaul
- weather extreme
- rule-era boundary

Any regime detector must itself be point-in-time-safe.

## P8 — Deep sequence models

Do **not** build a sequence transformer merely because v0.14 has created a richer state machine.

A neural sequence model becomes justified only when:

1. transparent play, role, drive, and transition models are competitive;
2. residual analysis shows stable serial dependence not explained by their state variables;
3. the sequence challenger is evaluated in the same expanding frozen protocol;
4. calibration and downstream fantasy distributions improve without leakage.

The project objective is a better probabilistic football world model, not a larger model for its own sake.
