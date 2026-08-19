# v0.15 Experiment Queue and v0.16 Router

The next layer must be chosen from expanding replay evidence rather than model size.

## P0 — Run v0.15 smoke then full replay

Default evidence window:

- acquire 2021–2025 history
- hold out 2023, 2024 and 2025
- Weeks 1–18
- smoke first
- begin full mode at 15 simulations per game/variant
- increase Monte Carlo draws only if paired comparisons remain noisy

Inspect pooled metrics, weekly win rates, and segment results by field zone, yards to go, team and season.

## P1 — Latent drive strategy state

Choose this only when:

- the learned fourth-down policy beats the frozen heuristic and permutation control;
- the termination hazard also carries independent signal;
- downstream action frequency, scoring and fantasy distributions improve or remain safe.

Start with a transparent persistent state model before any transformer:

- SCRIPTED
- NORMAL
- HURRY_UP
- COMEBACK
- CLOCK_CONTROL
- RED_ZONE_PACKAGE

Required test: persistent state must improve held-out future within-drive action / pace / play likelihood after conditioning on currently observable state.

## P2 — Fourth-down execution outcomes

Choose this when the action model predicts historical choices well but does not improve simulated action frequencies or downstream results.

Potential decomposition:

`decision → execution → terminal transition`

For `GO`:

- conversion probability
- play-family selection
- turnover risk
- explosive conversion

For `PUNT`:

- punt distance
- touchback
- return / fair catch
- block

For `FIELD_GOAL`:

- make probability
- block
- return after short miss where applicable

Do not hide a bad policy model inside a richer execution model.

## P3 — Richer fourth-down context

Choose this if the transparent action model fails the frozen heuristic or negative control.

Candidate point-in-time evidence:

- head coach / play caller identity
- QB starter
- remaining timeouts
- exact score / clock interaction
- pregame spread and total
- in-game win-probability state if derived without future leakage
- roof / stadium
- archived forecast wind / temperature
- rule-era boundary

A larger model is not justified until these obvious missing variables are tested.

## P4 — Terminal-family generation

Choose this if the binary drive-termination hazard is strong but team play volume remains weak.

The next model should estimate terminal family explicitly:

- CONTINUE
- SCORE
- TURNOVER
- DOWNS
- END_HALF

Only after terminal-family calibration should the hazard receive generative simulator authority.

Required controls:

- team/base hazard
- down/field-zone empirical baseline
- season/context permutation
- v0.15 simulator parity with authority disabled

## P5 — Decomposed scoring transitions

Choose this if fourth-down frequencies improve but points/fantasy distributions do not.

Candidate heads:

- red-zone entry → TD / FG / turnover
- fourth-down conversion
- completion
- air-yards depth
- YAC
- pressure / sack
- rushing efficiency
- turnover probability
- touchdown conversion

The empirical outcome sampler remains the baseline.

## P6 — Kicker / punt / return state

Choose this only when residuals concentrate in special teams.

Candidate evidence:

- kicker identity and recent distance-specific history
- punter identity
- returner identity
- roof / stadium / surface
- archived forecast weather
- touchback rate
- return-yard distribution
- blocks

Keep special-teams player state separate from offensive player-state projections until downstream value is demonstrated.

## P7 — Coaching-regime segmentation

If fourth-down policy wins only in stable coaching regimes, model that evidence maturity explicitly.

Potential boundaries:

- head-coach change
- offensive play-caller change
- QB starter change
- major rule-era change

The regime detector must itself be point-in-time-safe.

## P8 — Deep sequence models

Do not build a transformer because the state machine is richer.

A sequence model becomes justified only if:

1. transparent play, opportunity, pace, transition and decision layers are competitive;
2. residual analysis shows stable serial dependence that those layers do not explain;
3. the sequence challenger is run under the same expanding replay;
4. calibration and downstream fantasy distributions improve;
5. negative controls rule out chronology leakage.

The objective is a better probabilistic football world model, not a larger architecture.
