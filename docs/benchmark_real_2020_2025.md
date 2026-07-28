# Real 2020–2025 nflverse benchmark

## Protocol

- Source: official nflverse weekly player-stat releases and official schedules.
- Population: regular-season QB, RB, WR, and TE player-games.
- Rows after filtering: 34,883 player-weeks.
- Warm-up: the 2020 regular season.
- Out-of-sample evaluation: every regular-season week from 2021 through 2025.
- Retraining: expanding window at each season boundary.
- Models: q10/q50/q90 histogram gradient-boosting regressors.
- Baselines: five-game rolling empirical quantiles and expanding historical position priors.
- Feature contract: explicit pregame allowlist. Raw same-game nflverse outcomes are excluded.
- Primary metric: mean pinball loss. Secondary metrics: q50 MAE, bias, empirical quantile rates, interval coverage, interval width, season stability, and position stability.

The exact input hashes are recorded in `artifacts/reports/benchmark_real/DATA_MANIFEST.json`. Reproduce the run with:

```bash
python scripts/run_real_benchmark.py
```

## Main result

The original pooled quantile engine beat the strongest baseline on six of seven targets by mean pinball loss.

| Target | Engine mean pinball | Best baseline | Improvement | Held-out seasons won |
|---|---:|---:|---:|---:|
| Fantasy points PPR | 1.3992 | 1.4846 | +5.76% | 5/5 |
| Passing yards | 20.7321 | 22.2285 | +6.73% | 4/5 |
| Receiving yards | 5.1094 | 5.4786 | +6.74% | 5/5 |
| Receptions | 0.4042 | 0.4185 | +3.42% | 5/5 |
| Rushing yards | 2.8579 | 3.1263 | +8.58% | 5/5 |
| Targets | 0.5298 | 0.5350 | +0.97% | 5/5 |
| Carries | 0.7844 | 0.5157 | -52.11% | 0/5 |

The gains are modest rather than miraculous, which is the correct shape for a credible first benchmark against strong recency baselines.

## Why carries failed

The pooled carries model mixed fundamentally different outcome processes. WR rows were numerous and 86.8% of them had zero carries. Their mass pulled the pooled conditional median toward zero for QB and RB rows.

Mean predicted q50 versus observed mean in the pooled model:

| Position | Predicted q50 | Observed mean |
|---|---:|---:|
| QB | approximately 0.00 | 3.46 |
| RB | approximately 0.03 | 7.76 |
| WR | approximately 0.00 | 0.18 |

A position-specific quantile diagnostic reduced carries MAE from **3.1442 to 1.5173** and mean pinball loss from **0.7844 to 0.5091**. That narrowly beat the rolling baseline at 0.5157. v0.3 therefore routes carries through independent position heads in the production `HybridQuantileModelBundle`.

## Calibration findings

The nominal q10-to-q90 interval should cover approximately 80% of outcomes.

- Fantasy points coverage was 81.8%, close to nominal overall.
- Receiving yards coverage was 85.3% and rushing yards 84.9%, indicating somewhat conservative intervals.
- Passing yards coverage was 71.7%, too narrow overall and especially important because the target is QB-only.
- Targets and receptions exceeded 90% coverage, suggesting intervals that are too wide or lower/upper quantiles that are biased outward.
- Calibration differs by position. Aggregate coverage is not enough for promotion.

The next calibration experiment should fit out-of-fold, target-and-position conformal adjustments using only prior seasons. It must report both coverage and interval width because perfect coverage from giant intervals is merely uncertainty wearing a trench coat.

## Model decisions

### Promoted into v0.3 architecture

- Explicit pregame feature allowlist.
- Target-specific feature families.
- Vectorized historical feature generation.
- Position-specific carries heads.
- Guarded continual batch retraining and model registry.

### Not yet activated

- Injury and practice features.
- Snap and route participation.
- News extraction.
- Public-context or persona features.
- Play-by-play sequence models.
- Tracking models.

## Recommended next experiments

1. Add out-of-fold conformal calibration by target and position.
2. Build snap share, route participation, team play volume, target share, and carry share as explicit opportunity heads.
3. Add official injury/practice/depth-chart evidence to participation and workload uncertainty.
4. Add transactions, quarterback changes, and offensive-line continuity.
5. Test licensed news-derived role evidence after objective availability features.
6. Test public player-context features last, as residual modifiers with strict timestamps and evidence ablations.

## Artifact map

```text
artifacts/reports/benchmark_real/
├── DATA_MANIFEST.json
├── REAL_BENCHMARK_REPORT.md
├── benchmark_engine_vs_best_baseline.csv
├── benchmark_season_metrics.csv
├── benchmark_position_metrics.csv
├── benchmark_quantile_calibration_all.csv
├── benchmark_season_wins.csv
├── benchmark_position_wins.csv
└── <target>/
    ├── *_predictions.csv
    ├── *_summary_metrics.csv
    ├── *_season_metrics.csv
    ├── *_position_metrics.csv
    ├── *_quantile_calibration.csv
    ├── *_interval_calibration.csv
    └── *_benchmark_report.md
```
