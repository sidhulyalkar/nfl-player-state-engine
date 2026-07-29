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
- React 19 + Express 5 Gemini frontend, packaged as an npm workspace for Node.js 22
- Deterministic overall and positional ranks on every fantasy decision board
- League-relative positional-needs endpoint and interactive heatmap
- Leakage-safe historical team-context endpoint and 2025 showcase artifact
- Research-summary and filtered historical-prediction replay endpoints, including actual-source coverage and promotion-gate results
- Persistent provenance metadata: data mode, model version, prediction timestamp, cutoff, explicitly labeled file modification time, missing inputs and identity coverage
- Search, sorting, CSV export, decision-type switching and responsive tables
- Server-side Gemini tool execution with a structured deterministic fallback when Gemini is unavailable
- Google AI Studio Build prompt and implementation guide

## Important scientific limits

- Historical snap/depth/injury features enforce schedule-derived, game-specific cutoffs, preserve ID-resolution metadata and distinguish source coverage from post-imputation feature availability. The completed 2022–2025 actual-source ablation rejected every challenger; none is promoted.
- Structured news and persona features remain unpromoted.
- Trade suggestions are based on roster utility approximations, not yet full correlated rest-of-season simulations.
- League imports need broader real-world fixture testing outside Sleeper.
- Synthetic demo fixtures are explicitly labeled and are not presented as predictive evidence.
- Unverified projection and schedule artifacts fail closed or display an explicit `UNVERIFIED` state; filesystem modification time is never presented as prediction freshness.
- The frontend is deployable on port 3000, but authentication, durable user persistence and hosted operations remain future production work.
