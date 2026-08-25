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

For every football player-week, the research adapter resolves the immutable ledger at that row's prediction cutoff. This matters because:

1. a later retraction or supersession must remove an earlier assertion only after the correction itself becomes available;
2. evidence half-life decay must be recalculated at the actual prediction cutoff rather than frozen at an earlier snapshot time.

An explicit `prediction_cutoff` is preferred. When it is unavailable, the operator falls back to `gameday - safety_lag_hours` using the configured safety lag. Invalid cutoffs fail closed.

The attached fields are labeled `research_only`. They are not routed through the activation registry and cannot become production features through this operator.

## Leakage-safe feature discovery

The laboratory does not discover candidate features by scanning every column whose name resembles an intelligence family.

The base and legacy family columns must first be admitted by the repository's leakage-safe `feature_columns_for_target()` allowlist. Only the cutoff-specific canonical prefixes are added explicitly afterward:

```text
official_structured_*
news_structured_*
```

This prevents same-week supervision such as a raw `opportunity_target_share` outcome from entering the objective-opportunity challenger merely because it shares an `opportunity_` prefix. Lagged/rolling opportunity context remains eligible when the normal pregame feature contract allows it.

## Source coverage is not claim prevalence

A critical distinction is preserved:

- **claim prevalence** asks whether the system found an active claim for a player-week;
- **source coverage** asks whether the relevant source family was actually observed/checked for that player-week.

No claim can be legitimate information. No source collection cannot.

The operator never infers source coverage from `snapshot_found`, missing values, or lack of claims. Source coverage must arrive through explicit `*_source_covered` fields. Coverage aliases are resolved row by row. If two populated aliases disagree, the evaluator fails closed. Malformed binary values also fail closed.

Activation-review eligibility requires source coverage to be measured on every evaluated player-week and to clear the configured coverage threshold. A partially populated coverage column is not treated as a complete measurement.

## Evidence provenance and tiers

Statistical success and evidence authority are separate concepts.

The evaluator reports:

```text
model_gate_passed
eligible_for_activation_review
```

`model_gate_passed` means only that the isolated predictive/control/calibration gates cleared. Synthetic data is allowed to exercise this machinery.

`eligible_for_activation_review` additionally requires evidence tier 2 (`MULTI_SEASON_ISOLATED`) or higher plus complete source-coverage measurement. Synthetic or unspecified evidence therefore cannot become activation-review eligible even if every model metric is favorable.

The operator does not expose a free-form `--evidence-tier` switch. Without an evidence provenance manifest it fails closed to Tier 0 (`SYNTHETIC_ONLY`). Tier-2+ provenance must provide all of:

```json
{
  "schema_version": 1,
  "authority": "research_evidence_only",
  "evidence_tier": 2,
  "frozen_sample_id": "official-availability-2021-2024-v1",
  "point_in_time_verified": true,
  "source_coverage_point_in_time_verified": true
}
```

The provenance manifest is SHA-256 recorded in the experiment manifest. A Tier-2+ label is rejected if the frozen sample ID, point-in-time evidence verification, or point-in-time source-coverage verification is missing.

This metadata establishes how the sample was constructed. It does not itself prove predictive lift.

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
- explicit source coverage and measurement rate;
- claim prevalence and measurement rate;
- contradiction rate when the canonical family exposes conflict diagnostics;
- finite-sample p-value and run-wide FDR q-value;
- explicit evidence tier and evidence-tier name.

The model gate blocks a family for insufficient sample size, single-season evidence, weak/inconsistent effect, a confidence interval crossing zero, FDR failure, identity-control failure, or material calibration regression.

The activation-review gate adds source-coverage and evidence-tier requirements on top of the model gate.

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

Synthetic tests validate the evaluator and its failure boundaries only. They are structurally prevented from clearing activation review.

## Operator

A normal unverified/mechanics run is Tier 0:

```bash
python scripts/run_structured_intelligence_ablation.py \
  --features data/processed/weekly_features_with_objective_context.parquet \
  --ledger-root artifacts/structured_intelligence \
  --source-coverage data/processed/intelligence_source_coverage.parquet \
  --target fantasy_points_ppr \
  --output-dir artifacts/intelligence_ablations/structured
```

A frozen historical experiment supplies a separately constructed provenance manifest:

```bash
python scripts/run_structured_intelligence_ablation.py \
  --features data/processed/weekly_features_with_objective_context.parquet \
  --ledger-root artifacts/structured_intelligence \
  --source-coverage data/processed/intelligence_source_coverage.parquet \
  --evidence-provenance-manifest artifacts/intelligence_evidence/provenance.json \
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

The manifest records input hashes, a digest of the immutable claim set, the evidence-provenance record and hash, Git SHA, operator thresholds, negative-control definitions, multiple-testing policy, experiment rows, output hashes, and the non-automatic authority boundary.

## Evidence acquisition strategy

The laboratory can evaluate all four families, but their evidence paths should not be treated as symmetric.

Objective official evidence should be backtested only where the source supplies defensible historical timestamps. Narrative evidence such as structured news or public player context should remain prospective unless its publication-time availability can be reconstructed without hindsight.

The preferred sequence is therefore:

1. build a frozen point-in-time official-availability/depth-role corpus with explicit source-coverage logs;
2. evaluate mechanism-near targets before fantasy points;
3. use the 2026 shadow season for prospectively collected structured news/public context;
4. require downstream fantasy-decision replay before any production activation discussion.

The absence of a recoverable historical narrative corpus is a reason to wait for prospective evidence, not a reason to weaken the timestamp contract.
