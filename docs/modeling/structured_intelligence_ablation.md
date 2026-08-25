# Structured Intelligence Ablation Laboratory

## Purpose

This laboratory answers a narrower question than the Structured Intelligence ledger:

> Does a timestamped intelligence family add stable out-of-sample information beyond the stronger evidence already available before the same prediction cutoff?

It is intentionally stacked on the immutable structured-claim boundary. It does not activate a feature family and it does not alter production forecasts.

## Frozen experiment staircase

The canonical comparison order is:

```text
numerical baseline
  -> official availability
  -> objective opportunity
  -> structured news
  -> public player context
```

Each rung is incremental. Structured news is therefore not rewarded for rediscovering an official injury designation or objective opportunity trend already present in the reference model. Public player context receives the strictest reference and remains the final research-only rung.

## Point-in-time claim materialization

Canonical official and news claims are not joined by carrying forward a precomputed latest snapshot.

For every football player-week, the research adapter resolves the immutable ledger at that row's prediction cutoff. This matters for two reasons:

1. a later retraction or supersession must remove an earlier assertion only after the correction itself becomes available;
2. evidence half-life decay must be recalculated at the actual prediction cutoff rather than frozen at an earlier snapshot time.

An explicit `prediction_cutoff` is preferred. When it is unavailable, the operator falls back to `gameday - safety_lag_hours` using the configured safety lag. Invalid cutoffs fail closed.

The attached fields are labeled `research_only`. They are not routed through the activation registry and cannot become production features through this operator.

## Source coverage is not claim prevalence

A critical distinction is preserved:

- **claim prevalence** asks whether the system found an active claim for a player-week;
- **source coverage** asks whether the relevant source family was actually observed/checked for that player-week.

No claim can be legitimate information. No source collection cannot.

The ablation operator never infers source coverage from `snapshot_found`, missing values, or a lack of claims. Activation-review eligibility requires an explicit `*_source_covered` field on the evaluated player-weeks. Missing coverage metadata is a blocker.

## Negative controls

Every candidate family receives two controls.

### Identity control

Only the candidate family is shuffled within:

```text
season x week x position
```

The stronger reference evidence remains untouched. The real candidate must beat this shuffled-family control with a positive paired 95% confidence-interval lower bound.

### Shifted-time leakage sensitivity

The next same-player, same-season observation for only the candidate family is deliberately moved backward in time.

This is a diagnostic control, never an activation-eligible challenger. Its purpose is to show how much apparent gain future information could manufacture if the timestamp boundary failed.

## Paired uncertainty and multiple testing

Primary family effects are computed on exact shared player-weeks using mean q10/q50/q90 pinball loss:

```text
effect = reference row loss - candidate row loss
```

Positive values favor the candidate.

Uncertainty resamples complete season-week blocks while preserving the row-weighted estimand. The effective bootstrap count is at least 200. Publication p-values use the finite-sample plus-one rule:

```text
p = (unfavorable bootstrap draws + 1) / (B + 1)
```

Benjamini-Hochberg correction is applied across the four incremental family tests in one run.

## Calibration and consistency guards

The report includes:

- paired player-weeks, seasons, and season-week blocks;
- reference/candidate mean pinball loss;
- q50 MAE;
- empirical 80% interval coverage;
- overall coverage-gap regression;
- supported position-level coverage-gap regression;
- season, position, and week consistency;
- identity-control effect and interval;
- shifted-time leakage advantage;
- explicit source coverage;
- claim prevalence;
- contradiction rate when the canonical family exposes conflict diagnostics;
- finite-sample p-value and run-wide FDR q-value.

The default research-review gate blocks a family for insufficient sample size, single-season evidence, weak/inconsistent effect, a confidence interval crossing zero, FDR failure, identity-control failure, missing/insufficient source coverage, or material calibration regression.

## Research-review gate is not promotion

The strongest result produced here is:

```text
eligible_for_activation_review = true
```

That means only that the isolated family earned human review for a later experiment. It does **not**:

- write an activation registry;
- set any family to `enabled`;
- change the direct quantile production champion;
- change live draft/waiver/trade/lineup decisions;
- prove downstream fantasy value;
- replace the 2026 live shadow-season requirement.

Synthetic tests validate the evaluator and its failure boundaries only. They are not evidence that any intelligence family improves real NFL forecasts.

## Operator

```bash
python scripts/run_structured_intelligence_ablation.py \
  --features data/processed/weekly_features_with_objective_context.parquet \
  --ledger-root artifacts/structured_intelligence \
  --source-coverage data/processed/intelligence_source_coverage.parquet \
  --target fantasy_points_ppr \
  --output-dir artifacts/intelligence_ablations/structured
```

By default, legacy `availability_` and `news_` columns are dropped before canonical ledger-derived official/news fields are attached, isolating the new evidence contract. `--include-legacy-intelligence` is an explicit research compatibility option.

Outputs include:

```text
point_in_time_features.parquet
incremental_evidence.csv
run_manifest.json
variants/<variant benchmark artifacts>
```

The manifest records input hashes, a digest of the immutable claim set, Git SHA, operator thresholds, negative-control definitions, multiple-testing policy, experiment rows, output hashes, and the non-automatic authority boundary.
