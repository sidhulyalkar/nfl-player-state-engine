# Multi-season benchmark: `fantasy_points_ppr`

All rows are walk-forward out-of-sample predictions. Lower MAE, RMSE, pinball loss, and calibration error are better.

## Overall comparison

| method          |   pinball_q10 |   pinball_q50 |     mae |    rmse |      bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|--------------:|--------------:|--------:|--------:|----------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine |      0.720016 |       2.19704 | 4.39409 | 6.27108 | -1.0741   |       1.28044 |            0.818159 |               14.5015 |        1.39917 |  28415 |
| rolling_5       |      0.82868  |       2.30874 | 4.61749 | 6.50792 | -0.437256 |       1.31644 |            0.805314 |               14.0095 |        1.48462 |  28415 |
| position_prior  |      0.78986  |       2.88445 | 5.76891 | 7.86092 | -1.55197  |       1.64541 |            0.890973 |               18.9383 |        1.77324 |  28415 |

## Position-specific comparison

| method          | position   |   pinball_q10 |   pinball_q50 |     mae |    rmse |       bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|:-----------|--------------:|--------------:|--------:|--------:|-----------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine | QB         |      1.19165  |       3.03979 | 6.07957 | 7.70543 | -0.793323  |       1.49195 |            0.737736 |               18.5113 |        1.9078  |   3180 |
| rolling_5       | QB         |      1.28219  |       3.20149 | 6.40299 | 8.15646 | -0.0600132 |       1.51071 |            0.761006 |               19.5477 |        1.99813 |   3180 |
| position_prior  | QB         |      1.39894  |       3.71904 | 7.43808 | 9.10256 |  0.923195  |       1.64773 |            0.808805 |               25.7262 |        2.25523 |   3180 |
| quantile_engine | RB         |      0.702073 |       2.2184  | 4.43679 | 6.43951 | -1.29631   |       1.3305  |            0.788095 |               14.3384 |        1.41699 |   7442 |
| rolling_5       | RB         |      0.823318 |       2.32266 | 4.64531 | 6.61943 | -0.543007  |       1.36964 |            0.804085 |               14.2206 |        1.50521 |   7442 |
| position_prior  | RB         |      0.794408 |       3.0669  | 6.13381 | 8.31425 | -2.05819   |       1.76407 |            0.894114 |               19.7665 |        1.87513 |   7442 |
| quantile_engine | TE         |      0.536715 |       1.7184  | 3.43681 | 5.01613 | -0.886618  |       1.05528 |            0.876395 |               12.4048 |        1.10347 |   5914 |
| rolling_5       | TE         |      0.633695 |       1.82306 | 3.64611 | 5.21939 | -0.449319  |       1.07937 |            0.810112 |               10.5851 |        1.17871 |   5914 |
| position_prior  | TE         |      0.557099 |       2.15425 | 4.30851 | 6.2384  | -1.75921   |       1.35778 |            0.898546 |               13.7912 |        1.35638 |   5914 |
| quantile_engine | WR         |      0.696257 |       2.19636 | 4.39271 | 6.29848 | -1.1034    |       1.30457 |            0.829531 |               14.5741 |        1.39906 |  11879 |
| rolling_5       | WR         |      0.807711 |       2.30284 | 4.60569 | 6.51823 | -0.465988  |       1.34914 |            0.815557 |               14.0995 |        1.48657 |  11879 |
| position_prior  | WR         |      0.739842 |       2.91026 | 5.82053 | 7.93418 | -1.79427   |       1.71363 |            0.907231 |               19.1648 |        1.78791 |  11879 |

## Quantile calibration summary

| method          |   mean_absolute_calibration_error |
|:----------------|----------------------------------:|
| position_prior  |                         0.0325963 |
| quantile_engine |                         0.0449824 |
| rolling_5       |                         0.0594333 |

## Promotion gate

Do not add news, persona, tracking, or deeper sequence models until the quantile engine demonstrates a stable improvement over both baselines across multiple held-out seasons and its intervals are acceptably calibrated by position.
