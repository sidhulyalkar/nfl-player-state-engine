# Architecture

## Boundaries

The engine separates seven concerns:

1. **Acquisition:** immutable snapshots from public or licensed sources.
2. **State construction:** strictly pregame features derived from earlier observations.
3. **Benchmarking:** identical walk-forward folds for the engine and transparent baselines.
4. **Prediction:** calibrated distributions for opportunity and outcomes.
5. **Simulation:** correlated samples that maintain game-level dependence.
6. **Intelligence:** timestamped availability, news, and public-context evidence.
7. **Evaluation:** archived out-of-sample forecasts and paper-only market comparisons.

No source fetch occurs during model fitting. No current-week outcome is permitted in a current-week feature. No intelligence snapshot published after the cutoff can enter a prediction row. No paper-market result is allowed to overwrite the original prediction artifact.

## Data layers

- `data/raw`: immutable nflverse source snapshots
- `data/external/intelligence`: public-document registries, API caches, and raw evidence
- `data/interim`: canonicalized and joined tables
- `data/processed`: model-ready weekly features, intelligence snapshots, and slates
- `artifacts/models`: serialized estimators and manifests
- `artifacts/predictions`: timestamped forecasts
- `artifacts/reports`: metrics, calibration, simulations, evidence, and paper ledgers

## Benchmark contract

All benchmark methods receive the same train and test weeks. Baseline quantiles are estimated from the training window only. Predictions are persisted before aggregation. Position-level calibration is a first-class artifact, not an appendix assembled after a model wins.

## Intelligence contract

Collectors emit `PublicDocument` records with source URL, authored time, collection time, platform, content hash, and metadata. Extractors emit numeric snapshots plus evidence references. The point-in-time join uses the latest snapshot known before kickoff with a safety lag.

The intelligence layer is optional and disabled by default. Network connectors are credential-driven and imported lazily, so the numerical model remains runnable offline.

## Extension seams

New sources should implement a collector or loader that preserves publication and collection timestamps. New models should consume the same feature/slate contract and emit `<target>_q10`, `<target>_q50`, and `<target>_q90` columns. This keeps simulation and evaluation independent of model family.
