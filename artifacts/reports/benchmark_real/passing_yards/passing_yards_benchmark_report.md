# Multi-season benchmark: `passing_yards`

All rows are walk-forward out-of-sample predictions. Lower MAE, RMSE, pinball loss, and calibration error are better.

## Overall comparison

| method          |   pinball_q10 |   pinball_q50 |     mae |     rmse |     bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|--------------:|--------------:|--------:|---------:|---------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine |       14.0497 |       32.9972 | 65.9944 |  84.3208 |  8.76435 |       15.1493 |            0.717296 |               191.56  |        20.7321 |   3180 |
| rolling_5       |       14.8382 |       35.4888 | 70.9776 |  90.2789 |  1.48237 |       16.3584 |            0.795912 |               218.156 |        22.2285 |   3180 |
| position_prior  |       19.2456 |       40.7075 | 81.4151 | 105.222  | 24.4689  |       16.4183 |            0.825472 |               306.209 |        25.4572 |   3180 |

## Position-specific comparison

| method          | position   |   pinball_q10 |   pinball_q50 |     mae |     rmse |     bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|:-----------|--------------:|--------------:|--------:|---------:|---------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine | QB         |       14.0497 |       32.9972 | 65.9944 |  84.3208 |  8.76435 |       15.1493 |            0.717296 |               191.56  |        20.7321 |   3180 |
| rolling_5       | QB         |       14.8382 |       35.4888 | 70.9776 |  90.2789 |  1.48237 |       16.3584 |            0.795912 |               218.156 |        22.2285 |   3180 |
| position_prior  | QB         |       19.2456 |       40.7075 | 81.4151 | 105.222  | 24.4689  |       16.4183 |            0.825472 |               306.209 |        25.4572 |   3180 |

## Quantile calibration summary

| method          |   mean_absolute_calibration_error |
|:----------------|----------------------------------:|
| rolling_5       |                         0.0206499 |
| position_prior  |                         0.0314465 |
| quantile_engine |                         0.0425577 |

## Promotion gate

Do not add news, persona, tracking, or deeper sequence models until the quantile engine demonstrates a stable improvement over both baselines across multiple held-out seasons and its intervals are acceptably calibrated by position.
