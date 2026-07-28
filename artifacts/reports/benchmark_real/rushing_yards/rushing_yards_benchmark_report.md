# Multi-season benchmark: `rushing_yards`

All rows are walk-forward out-of-sample predictions. Lower MAE, RMSE, pinball loss, and calibration error are better.

## Overall comparison

| method          |   pinball_q10 |   pinball_q50 |      mae |    rmse |      bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|--------------:|--------------:|---------:|--------:|----------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine |       1.33117 |       4.26847 |  8.53694 | 18.319  | -3.8454   |       2.97407 |            0.849384 |               25.6124 |        2.8579  |  22501 |
| rolling_5       |       1.77219 |       4.62378 |  9.24756 | 18.4381 | -0.614169 |       2.98288 |            0.792276 |               24.6813 |        3.12628 |  22501 |
| position_prior  |       1.46256 |       5.79872 | 11.5974  | 23.5    | -5.19617  |       3.86764 |            0.870584 |               34.5869 |        3.70964 |  22501 |

## Position-specific comparison

| method          | position   |   pinball_q10 |   pinball_q50 |      mae |     rmse |        bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|:-----------|--------------:|--------------:|---------:|---------:|------------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine | QB         |      1.73558  |      5.59269  | 11.1854  | 17.3603  |  -5.11864   |      3.49819  |            0.725786 |              33.6116  |       3.60882  |   3180 |
| rolling_5       | QB         |      2.29918  |      5.84161  | 11.6832  | 17.2639  |  -1.32921   |      3.58552  |            0.688679 |              30.4215  |       3.90877  |   3180 |
| position_prior  | QB         |      1.76377  |      6.97343  | 13.9469  | 21.8656  |  -8.05031   |      4.71618  |            0.783962 |              42.8989  |       4.48446  |   3180 |
| quantile_engine | RB         |      3.00298  |      9.58412  | 19.1682  | 29.1947  |  -7.90589   |      6.12384  |            0.771298 |              54.6073  |       6.23698  |   7442 |
| rolling_5       | RB         |      3.67486  |     10.1107   | 20.2214  | 29.412   |  -1.42191   |      6.14313  |            0.793335 |              59.0731  |       6.64289  |   7442 |
| position_prior  | RB         |      3.38795  |     13.6137   | 27.2275  | 37.8128  | -10.6244    |      8.09343  |            0.880677 |              83.4198  |       8.36504  |   7442 |
| quantile_engine | WR         |      0.175545 |      0.583804 |  1.16761 |  4.58396 |  -0.960715  |      0.860489 |            0.931392 |               5.30614 |       0.539946 |  11879 |
| position_prior  | WR         |      0.175705 |      0.588265 |  1.17653 |  4.72477 |  -1.0314    |      0.993107 |            0.887448 |               1.76885 |       0.585692 |  11879 |
| rolling_5       | WR         |      0.439115 |      0.86031  |  1.72062 |  4.71303 |   0.0832842 |      0.841717 |            0.819345 |               1.59866 |       0.713714 |  11879 |

## Quantile calibration summary

| method          |   mean_absolute_calibration_error |
|:----------------|----------------------------------:|
| position_prior  |                          0.16251  |
| quantile_engine |                          0.176839 |
| rolling_5       |                          0.201027 |

## Promotion gate

Do not add news, persona, tracking, or deeper sequence models until the quantile engine demonstrates a stable improvement over both baselines across multiple held-out seasons and its intervals are acceptably calibrated by position.
