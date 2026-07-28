# Multi-season benchmark: `carries`

All rows are walk-forward out-of-sample predictions. Lower MAE, RMSE, pinball loss, and calibration error are better.

## Overall comparison

| method          |   pinball_q10 |   pinball_q50 |     mae |   rmse |      bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|--------------:|--------------:|--------:|-------:|----------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| rolling_5       |      0.3006   |      0.789161 | 1.57832 | 3.0433 | -0.103048 |      0.457361 |            0.826497 |               4.76134 |       0.515707 |  22501 |
| position_prior  |      0.31515  |      1.15426  | 2.30852 | 4.3481 | -0.743078 |      0.635147 |            0.943114 |               7.58955 |       0.701519 |  22501 |
| quantile_engine |      0.314558 |      1.5721   | 3.14421 | 6.2674 | -3.14067  |      0.466615 |            0.919959 |               5.81606 |       0.784425 |  22501 |

## Position-specific comparison

| method          | position   |   pinball_q10 |   pinball_q50 |      mae |      rmse |       bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|:-----------|--------------:|--------------:|---------:|----------:|-----------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| rolling_5       | QB         |     0.359015  |     0.934696  | 1.86939  |  2.50386  | -0.181336  |      0.486363 |            0.809748 |              5.47682  |      0.593358  |   3180 |
| position_prior  | QB         |     0.345786  |     1.09811   | 2.19623  |  3.05052  | -0.457862  |      0.675016 |            0.922642 |              7.84198  |      0.706305  |   3180 |
| quantile_engine | QB         |     0.345786  |     1.72893   | 3.45786  |  4.58834  | -3.45786   |      0.481834 |            0.902516 |              6.71133  |      0.852184  |   3180 |
| rolling_5       | RB         |     0.68021   |     1.79936   | 3.59871  |  4.99183  | -0.242492  |      0.999549 |            0.817925 |             11.0362   |      1.1597    |   7442 |
| position_prior  | RB         |     0.776404  |     2.87718   | 5.75437  |  7.25598  | -1.76404   |      1.42443  |            0.910911 |             18        |      1.69267   |   7442 |
| quantile_engine | RB         |     0.774613  |     3.87099   | 7.74198  | 10.4514   | -7.73127   |      1.00818  |            0.865493 |             12.8085   |      1.88459   |   7442 |
| quantile_engine | WR         |     0.0179813 |     0.0899066 | 0.179813 |  0.579993 | -0.179813  |      0.12326  |            0.958751 |              1.19575  |      0.0770494 |  11879 |
| position_prior  | WR         |     0.0179813 |     0.0899066 | 0.179813 |  0.579993 | -0.179813  |      0.130003 |            0.968768 |              1        |      0.0792968 |  11879 |
| rolling_5       | WR         |     0.0471417 |     0.117332  | 0.234663 |  0.503992 |  0.0052698 |      0.109925 |            0.83635  |              0.638739 |      0.091466  |  11879 |

## Quantile calibration summary

| method          |   mean_absolute_calibration_error |
|:----------------|----------------------------------:|
| position_prior  |                          0.160697 |
| rolling_5       |                          0.166409 |
| quantile_engine |                          0.225671 |

## Promotion gate

Do not add news, persona, tracking, or deeper sequence models until the quantile engine demonstrates a stable improvement over both baselines across multiple held-out seasons and its intervals are acceptably calibrated by position.
