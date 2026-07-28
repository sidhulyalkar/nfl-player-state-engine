# Current package state: v0.6

## Research core

- Real 2020–2025 walk-forward benchmark
- Quantile projections with q10/q50/q90
- Target-aware and position-aware models
- Conformal calibration using earlier-season residuals
- Correlated game simulation
- Champion/challenger continual-learning scaffold
- Immutable source and prediction artifacts

## Football context

- Weekly player-state features
- Opportunity-head architecture
- Snap, participation, depth, injury, roster, combine, draft, and play-by-play acquisition scaffolds
- Team play-structure and scheme-fit features
- Rookie priors and analog model
- Official availability, structured news, and public-context evidence families

## Fantasy decision layer

- League scoring and replacement levels
- Start/sit, waiver, trade, draft, stash, and dynasty boards
- Legal lineup optimization
- High-chance opportunity watchlists
- FAAB planning
- League-relative player values

## Product layer added in v0.6

- Canonical `LeagueSnapshot`
- Sleeper importer
- Generic CSV importer
- Yahoo OAuth and Fleaflicker boundaries
- Filesystem league snapshot store
- Ownership matrix and league power rankings
- NFL standings/state builder
- Two-sided trade evaluation
- Mutually beneficial trade suggestion search
- FastAPI Product API
- React + Node Gemini frontend scaffold
- Google AI Studio Build prompt and implementation guide

## Important scientific limits

- Historical snap/depth/injury source-family ablations still need to be run locally with downloaded release binaries.
- Structured news and persona features remain unpromoted.
- Trade suggestions are based on roster utility approximations, not yet full correlated rest-of-season simulations.
- League imports need broader real-world fixture testing outside Sleeper.
- The frontend ships as a product scaffold and demo, not a hosted production service.
