# Model Card: Hybrid Quantile Player Engine v0.3

## Intended use

Weekly NFL player projection research, fantasy decision support, simulation, calibrated uncertainty analysis, and paper-only market evaluation.

## Out-of-scope use

Automated wagering, profit guarantees, injury diagnosis, private-person profiling, or decisions made without checking source freshness and player availability.

## Architecture

The production bundle fits q10, q50, and q90 estimators for supported targets.

- Most targets use pooled histogram gradient-boosting quantile models.
- Carries uses independent position-specific heads because the 2020–2025 benchmark showed severe pooled zero-inflation failure.
- Quantiles are sorted after prediction to prevent crossing.
- A correlated Monte Carlo layer converts player marginals into slate simulations.

## Training data

User-selected nflverse weekly player statistics and schedules. The bundled real benchmark uses regular-season data from 2020–2025, with 2020 as warm-up and 2021–2025 out of sample. Raw source files are not redistributed; source URLs, sizes, and SHA-256 hashes are recorded.

## Outputs

q10, q50, and q90 estimates for:

- PPR fantasy points;
- targets;
- carries;
- receptions;
- receiving yards;
- rushing yards;
- passing yards.

## Evaluation

Temporal holdout and expanding-window backtesting using:

- mean and per-quantile pinball loss;
- q50 MAE, RMSE, and bias;
- empirical q10/q50/q90 rates;
- q10-to-q90 coverage and width;
- held-out season stability;
- position-specific performance;
- rolling-5 and position-prior baselines.

## Real benchmark summary

The original pooled engine beat the strongest baseline on six of seven targets. Carries failed decisively. A position-specific carries diagnostic reduced mean pinball loss from 0.7844 to 0.5091, compared with 0.5157 for rolling-5, and is integrated in the v0.3 production bundle.

Known calibration problems remain: passing-yard intervals are too narrow overall, while target and reception intervals are too conservative.

## Known risks

Role changes, inactive players, rookies, trades, stat revisions, late injury news, correlated errors, changing systems, sparse tails, selection bias, source schema changes, and non-stationarity across seasons.

## Optional intelligence features

Availability and public-context scaffolds are disabled by default. All intelligence must join point in time with a safety lag. Public-context outputs summarize observable football-related language with evidence links. They are not stable personality truth, sensitive-trait inference, or clinical/psychological assessment.

## Continual learning

The engine supports guarded expanding-window challengers. It does not perform uncontrolled online updates. Candidates must pass baseline, coverage, and position-regression gates. Automatic champion promotion is disabled by default.

## Promotion requirement

No deeper model or intelligence feature replaces the champion unless it improves frozen walk-forward metrics across seasons and eligible positions without materially degrading calibration or interval sharpness. Every promotion should preserve predictions, source hashes, config, and review notes.

## Ethical and legal note

The model is not evidence of a profitable wagering strategy. Keep monetary evaluation paper-only while validity is uncertain. Public-content collection must honor access boundaries and must not circumvent login or challenge mechanisms.

## v0.4 calibration and intelligence controls

Continual challenger artifacts may embed a `TargetPositionConformalCalibrator` fitted only on archived out-of-sample residuals. Calibration must never be fitted on the same season used to report performance.

The opportunity model uses temporal cross-fitting so downstream heads receive predicted, not observed, upstream states. Missing snap, route, red-zone and offensive-line sources are represented as missing with explicit availability indicators.

Official, news and public-context evidence are disabled by default. Soft evidence should first enter through `IntelligenceResidualAdjuster`, which caps center shifts and uncertainty scaling. Every intelligence experiment must include shuffled-player and shifted-time controls.

Known limitations:

- deterministic intervals are conservative for zero-inflated count targets such as receptions;
- real opportunity-head validation requires a complete point-in-time snap and route participation archive;
- public posts are selective and can reflect media strategy rather than football state;
- source coverage differs by player and can create visibility bias;
- no intelligence family has yet earned production promotion through the full real-data ablation suite.
