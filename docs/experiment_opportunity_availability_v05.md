# Frozen opportunity and availability experiment, v0.5

## Question

Does adding strictly lagged box-score opportunity history and historical participation proxies improve the frozen out-of-sample fantasy-point engine?

## Data and protocol

- 23,003 out-of-sample QB/RB/WR/TE player-weeks from the 2021–2025 frozen benchmark archive.
- Each test season is predicted using models trained only on earlier seasons.
- The numerical q10/q50/q90 predictions are frozen.
- Residual adjustments are capped at 30% of the original interval half-width.
- Opportunity inputs include lagged carries, targets, receptions, passing/rushing/receiving yards, team shares, recent role trends, and team volume.
- Participation-history inputs include prior active indicators, five-game active rate, and gaps between observed player-weeks.
- These participation variables are **not official injury reports**.

## Overall result

| Variant | MAE | RMSE | Mean pinball | 80% coverage | Pinball vs baseline |
|---|---:|---:|---:|---:|---:|
| Numerical baseline | 4.3311 | 6.2229 | 1.3803 | 82.1% | 0.00% |
| Objective opportunity | 4.4454 | 6.1141 | 1.4295 | 67.1% | -3.57% |
| Objective + participation | 4.4334 | 6.1064 | 1.4237 | 67.3% | -3.14% |
| Future-shift leakage control | 2.6505 | 4.7648 | 1.0071 | 90.7% | 27.04% |

## Interpretation

The objective features do not earn promotion. They slightly reduce RMSE but worsen MAE and probabilistic loss, while collapsing coverage. This is consistent with redundancy: the frozen numerical engine already contains lagged performance and usage statistics, so a residual layer built from repackaged box-score history mostly overfits.

The future-shift control improves pinball by 27.0%, demonstrating that the pipeline is sensitive enough to detect leaked role information. This is a useful positive control, not a deployable model.

The only mild subgroup signal is QB, where objective plus participation history changes mean pinball from 1.8967 to 1.8922. That isolated gain is too small and inconsistent to promote.

## Decision

1. Keep the numerical champion unchanged.
2. Do not activate box-score opportunity residuals.
3. Acquire genuinely new point-in-time sources: offensive snaps, pass-play participation or routes, depth charts, official practice/game status, inactive lists, and transactions.
4. Re-run the exact frozen protocol with each source family separately.
5. Treat official availability as an upstream active/snap-share feature, not a free-form fantasy-point correction.

## Source acquisition status

The repository now contains a deterministic downloader and checksum manifest for nflverse snap counts, participation, play-by-play, injuries, depth charts, weekly rosters, combine data, and draft picks. Binary release assets could not be transferred into the isolated artifact runtime, so no official-availability performance claim is made in this release. Run `python scripts/acquire_historical_sources.py` in a networked local environment, then execute the future-source ablation workflow.
