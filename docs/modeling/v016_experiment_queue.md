# v0.16 Experiment Queue and v0.17 Router

The v0.17 branch must be chosen from held-out replay evidence. Do not treat a cleaner architecture as evidence that a deeper model is necessary.

## P0 — Execute v0.16 smoke then full replay

Default evidence window:

- acquire 2021–2025 history;
- hold out 2023, 2024 and 2025;
- regular-season Weeks 1–18;
- run smoke first with one game/week and one simulation/cell;
- begin full mode at eight simulations/game/cell;
- increase Monte Carlo draws only if paired terminal-authority comparisons remain noisy.

Inspect:

- joint terminal-family log loss / Brier / ECE;
- conditional terminal-family log loss;
- canonical termination hazard;
- full and conditional permutation controls;
- per-family recall and Brier;
- conditioned-outcome fallback rate;
- terminal event MAE in all four parent contexts;
- drives, plays, pace, points, opportunity and fantasy distributions;
- season/week/team/field-zone/down residuals.

## P1 — Latent drive strategy state

Choose this only when terminal family transfers safely into simulation and the earlier play/decision layers are also competitive.

Start with a transparent persistent latent state rather than attention:

- `SCRIPTED`
- `NORMAL`
- `HURRY_UP`
- `COMEBACK`
- `CLOCK_CONTROL`
- `RED_ZONE_PACKAGE`

Required experiment:

`observable state only` vs `observable state + inferred persistent drive state`

under expanding weekly replay.

The latent state must improve future within-drive play-family, pace or terminal likelihood after conditioning on currently observable state.

## P2 — Decomposed scoring and execution

Choose this when terminal timing/family improves but points or fantasy distributions regress.

Separate outcome heads can then target:

- pressure / sack;
- completion;
- air yards;
- YAC;
- rushing efficiency;
- turnover execution;
- touchdown conversion;
- fourth-down conversion.

The current empirical outcome sampler remains the baseline. Preserve within-play correlation when recombining heads.

## P3 — Richer terminal-family context

Choose this when canonical termination hazard has signal but conditional family does not.

Candidate timestamp-safe inputs:

- head coach / offensive play caller;
- starting QB;
- remaining timeouts;
- exact score × clock interaction;
- pregame spread / total;
- red-zone series state;
- goal-to-go state;
- roof / stadium / surface;
- archived forecast wind / temperature;
- rule-era boundaries.

Test obvious missing variables before model depth.

## P4 — Terminal-authority mechanics audit

Choose this when isolated family classification is good but simulator terminal frequencies do not improve.

Audit:

- family-conditioned empirical support;
- fallback concentration by family / play type;
- structural masks for DOWNS / END_HALF;
- interactions with fourth-down policy;
- clock-boundary handling;
- transition-model interaction;
- whether outcome conditioning changes yards/first-down distributions in unintended ways.

Do not respond to a transfer failure by immediately training a larger family classifier.

## P5 — Drive strategy and continuation state

Choose this when terminal labels are learnable but plays/drive or total play volume remain weak.

Candidate mechanisms:

- drive-start script state;
- conversion-chain persistence;
- no-huddle state;
- score-state pace regime;
- first-down continuation propensity;
- opponent pace interaction;
- possession objective / clock management.

This layer should predict state transitions, not just regress aggregate plays/game.

## P6 — Coaching / QB regime segmentation

Choose this if terminal-family performance is unstable across regime changes.

Point-in-time regime boundaries can include:

- head-coach change;
- play-caller change;
- QB starter change;
- major offensive-line disruption;
- rule-era change.

The maturity / confidence of a regime estimate should itself be explicit evidence.

## P7 — Special-teams state

Choose this only if residual downstream errors concentrate after punts, field goals, or returns rather than scrimmage terminal families.

Candidate evidence:

- kicker identity and distance-specific form;
- punter identity;
- returner identity;
- touchback rate;
- return-yard distribution;
- blocks;
- roof / stadium / wind.

Keep special-teams player state separate from offensive role state until downstream value is demonstrated.

## P8 — Clock / timeout strategy

Choose this if END_HALF or late-game residuals dominate while non-clock terminal families are calibrated.

Candidate state:

- exact clock;
- timeout inventory;
- score differential;
- possession expectation;
- kneel / spike availability;
- sideline / completion clock-stop outcomes;
- two-minute warning where applicable.

A dedicated clock-state model should own time mechanics rather than corrupting terminal-family labels.

## P9 — Deep sequence challenger

A transformer or recurrent sequence model is justified only after:

1. transparent play, opportunity, pace, transition, fourth-down and terminal-family layers are competitive;
2. residual analysis shows stable serial dependence not explained by those states;
3. the sequence model uses identical point-in-time folds and negative controls;
4. calibration improves, not just likelihood;
5. downstream game and fantasy distributions improve;
6. chronology leakage controls pass.

The goal remains a better probabilistic football world model, not architectural ornament.
