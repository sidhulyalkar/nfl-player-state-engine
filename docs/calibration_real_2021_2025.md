# Earlier-season conformal calibration: real 2021–2025 evaluation

## Contract

For each test season, corrections were fitted only from out-of-sample residuals in earlier seasons:

- 2021: emitted unchanged because no earlier out-of-sample season existed;
- 2022: calibrated from 2021;
- 2023: calibrated from 2021–2022;
- 2024: calibrated from 2021–2023;
- 2025: calibrated from 2021–2024.

Corrections are target- and position-specific with shrinkage toward a target-wide fallback. Additive residual corrections adjust location; tail scaling around q50 widens or contracts q10/q90.

## Overall results

| Target | Raw coverage | Calibrated coverage | Raw pinball | Calibrated pinball | Interpretation |
|---|---:|---:|---:|---:|---|
| Passing yards | 71.73% | **81.04%** | 20.7321 | 20.8197 | Coverage fixed; small 0.42% pinball cost |
| Targets | 90.17% | **83.73%** | 0.5298 | **0.5266** | Sharper and modestly better loss |
| Receptions | 90.57% | 90.69% | 0.4042 | **0.4034** | Small loss gain; deterministic interval remains conservative |
| Fantasy PPR | 81.82% | 83.85% | 1.3992 | **1.3970** | Small loss gain; position coverage still differs |
| Receiving yards | 85.25% | 86.40% | 5.1094 | **5.0955** | Small loss gain but wider than desired |
| Rushing yards | 84.94% | 86.05% | 2.8579 | 2.8629 | Slight loss regression; do not promote on this target yet |
| Carries, frozen pooled engine | 92.00% | 90.50% | 0.7844 | **0.6713** | Large correction, but production already uses position heads |

## Position findings

Fantasy PPR raw coverage varied substantially:

- QB: 73.77% → 76.38%
- RB: 78.81% → 81.94%
- TE: 87.64% → 87.42%
- WR: 82.95% → 85.27%

The calibrator improves QB/RB undercoverage but does not solve TE/WR conservatism. Calibration remains target-position specific, and promotion gates should inspect each eligible position rather than rely on the aggregate.

Target coverage improved most where deterministic intervals can move continuously:

- RB: 92.22% → 91.28%
- TE: 91.39% → 81.59%
- WR: 88.27% → 80.07%

## Discrete-target caveat

Receptions and targets contain a large mass at zero. For some position/state cohorts, q10 and q50 are both zero. A deterministic q10 endpoint then includes every zero outcome and cannot achieve exactly 10% lower-tail frequency. This makes q10–q90 coverage naturally conservative even when q90 is well calibrated.

Future discrete heads should emit a zero-inflated distribution:

1. probability of zero;
2. positive-count distribution conditional on nonzero;
3. quantiles sampled or derived from the mixture.

Until then, report both marginal quantile calibration and interval coverage, and do not widen/shrink intervals solely to force a nominal 80% number.

## Artifacts

All generated files are under:

```text
artifacts/reports/conformal_real/
```

Reproduce with:

```bash
python scripts/run_conformal_benchmark.py
```
