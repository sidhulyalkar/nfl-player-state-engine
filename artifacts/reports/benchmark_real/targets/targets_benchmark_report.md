# Multi-season benchmark: `targets`

All rows are walk-forward out-of-sample predictions. Lower MAE, RMSE, pinball loss, and calibration error are better.

## Overall comparison

| method          |   pinball_q10 |   pinball_q50 |     mae |    rmse |      bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|--------------:|--------------:|--------:|--------:|----------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine |      0.331756 |      0.807302 | 1.6146  | 2.24529 | -0.292142 |      0.45026  |            0.901684 |               6.19543 |       0.529773 |  25235 |
| rolling_5       |      0.312569 |      0.835961 | 1.67192 | 2.31745 | -0.120284 |      0.456416 |            0.824648 |               5.10148 |       0.534982 |  25235 |
| position_prior  |      0.3332   |      1.16535  | 2.33069 | 3.10022 | -0.408203 |      0.635463 |            0.91381  |               7.59945 |       0.711336 |  25235 |

## Position-specific comparison

| method          | position   |   pinball_q10 |   pinball_q50 |     mae |    rmse |      bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|:-----------|--------------:|--------------:|--------:|--------:|----------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine | RB         |      0.205391 |      0.656685 | 1.31337 | 1.83157 | -0.191534 |      0.382461 |            0.922198 |               4.76478 |       0.414845 |   7442 |
| rolling_5       | RB         |      0.23164  |      0.675404 | 1.35081 | 1.89812 | -0.131741 |      0.383834 |            0.832438 |               4.02913 |       0.430293 |   7442 |
| position_prior  | RB         |      0.205442 |      0.840365 | 1.68073 | 2.22957 | -0.159635 |      0.483351 |            0.91763  |               5       |       0.50972  |   7442 |
| quantile_engine | TE         |      0.313168 |      0.73443  | 1.46886 | 2.04613 | -0.266741 |      0.414658 |            0.913933 |               5.97306 |       0.487418 |   5914 |
| rolling_5       | TE         |      0.300567 |      0.764561 | 1.52912 | 2.11269 | -0.118448 |      0.422374 |            0.814339 |               4.56359 |       0.495834 |   5914 |
| position_prior  | TE         |      0.316892 |      1.04244  | 2.08488 | 2.99588 | -1.11194  |      0.608252 |            0.882651 |               6.7117  |       0.655862 |   5914 |
| rolling_5       | WR         |      0.369246 |      0.972094 | 1.94419 | 2.63241 | -0.114021 |      0.518835 |            0.824901 |               6.04108 |       0.620058 |  11879 |
| quantile_engine | WR         |      0.420177 |      0.937942 | 1.87588 | 2.55411 | -0.367816 |      0.510461 |            0.882734 |               7.20241 |       0.62286  |  11879 |
| position_prior  | WR         |      0.421357 |      1.43013  | 2.86026 | 3.58262 | -0.21357  |      0.744305 |            0.92693  |               9.66992 |       0.865264 |  11879 |

## Quantile calibration summary

| method          |   mean_absolute_calibration_error |
|:----------------|----------------------------------:|
| quantile_engine |                         0.0482496 |
| position_prior  |                         0.0734423 |
| rolling_5       |                         0.0800097 |

## Promotion gate

Do not add news, persona, tracking, or deeper sequence models until the quantile engine demonstrates a stable improvement over both baselines across multiple held-out seasons and its intervals are acceptably calibrated by position.
