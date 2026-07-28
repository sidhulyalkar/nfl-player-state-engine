# Multi-season Benchmarking

## Purpose

The benchmark asks whether the quantile engine adds value beyond two hard-to-fool baselines under the same walk-forward protocol.

## Methods

### Quantile engine

Histogram gradient-boosting models trained independently for q10, q50, and q90. Production v0.3 routes carries through position-specific heads; the frozen pooled benchmark is retained to document the failure that motivated this change.

### Rolling baseline

A leakage-safe five-game rolling mean plus historical, position-conditioned residual quantiles. This baseline is stronger than simply copying the rolling mean into every quantile.

### Position prior

Historical q10, q50, and q90 outcome values for the player's position, estimated from the training window only.

## Reproduce the bundled real benchmark

```bash
python scripts/run_real_benchmark.py
```

This uses `configs/benchmark_real.yaml`: 2020 is the 17-week warm-up, models retrain at each later season boundary, and all 2021–2025 predictions are out of sample.

For a focused custom run:

```bash
pse benchmark-multiseason \
  --features data/processed/weekly_features_2020_2025.parquet \
  --target receiving_yards \
  --min-train-weeks 17 \
  --retrain-every 18 \
  --rolling-window 5 \
  --output-dir artifacts/reports/benchmark/receiving_yards
```

## Output interpretation

### Summary metrics

- `mean_pinball`: primary distributional score
- `mae`: q50 point error
- `bias`: mean q50 minus actual
- `interval_coverage`: empirical q10–q90 coverage
- `mean_interval_width`: sharpness, interpreted with coverage

### Quantile calibration

For a calibrated q10, approximately 10% of actual outcomes should be at or below the predicted q10. The same logic applies to q50 and q90.

Inspect absolute error, but do not demand exact nominal rates from tiny position samples. Use confidence intervals or grouped bootstrap before making promotion decisions.

### Fold stability

Aggregate improvement can hide a model that only wins in one season. Plot or summarize fold metrics by season and week. A useful model should avoid catastrophic collapses even when it does not win every fold.

## Initial promotion gate

A candidate is eligible for deeper experimentation when:

- it improves mean pinball loss against both baselines overall
- improvement appears in most eligible positions
- q50 bias is modest
- q10–q90 coverage is reasonably close to 80%
- intervals are not dramatically wider than the baselines
- gains are not isolated to one season

These are investigation gates, not claims of profitability.

## Required follow-up analyses

- error by player history count
- error after trades or team changes
- rookies versus veterans
- weeks after bye
- home versus away
- favored versus underdog
- high versus low game total
- inactive and zero-opportunity rows
- postseason versus regular season


## Completed result

See `docs/benchmark_real_2020_2025.md`. The pooled engine won six of seven targets. The position-specific carries correction then narrowly beat rolling-5 and is integrated into the production hybrid bundle.
