# Multi-season benchmark: `receiving_yards`

All rows are walk-forward out-of-sample predictions. Lower MAE, RMSE, pinball loss, and calibration error are better.

## Overall comparison

| method          |   pinball_q10 |   pinball_q50 |     mae |    rmse |     bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|--------------:|--------------:|--------:|--------:|---------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine |       2.43361 |       7.97083 | 15.9417 | 24.4248 | -5.01275 |       4.92379 |            0.852546 |               50.7341 |        5.10941 |  25235 |
| rolling_5       |       2.88464 |       8.45649 | 16.913  | 25.1958 | -1.70982 |       5.09459 |            0.808361 |               50.2183 |        5.47857 |  25235 |
| position_prior  |       2.48938 |      10.2702  | 20.5405 | 30.1879 | -7.39643 |       6.35156 |            0.896374 |               65.6177 |        6.37039 |  25235 |

## Position-specific comparison

| method          | position   |   pinball_q10 |   pinball_q50 |      mae |    rmse |      bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|:-----------|--------------:|--------------:|---------:|--------:|----------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine | RB         |       1.25548 |       4.92735 |  9.85469 | 15.5505 | -3.06519  |       3.42315 |            0.889949 |               33.4911 |        3.20199 |   7442 |
| rolling_5       | RB         |       1.72663 |       5.28425 | 10.5685  | 16.1553 | -0.994211 |       3.51754 |            0.796426 |               29.2111 |        3.50947 |   7442 |
| position_prior  | RB         |       1.2563  |       5.71607 | 11.4321  | 17.8663 | -5.62913  |       4.02919 |            0.883902 |               35.439  |        3.66719 |   7442 |
| quantile_engine | TE         |       2.25378 |       7.29541 | 14.5908  | 21.455  | -4.78291  |       4.30227 |            0.87352  |               48.7012 |        4.61715 |   5914 |
| rolling_5       | TE         |       2.71024 |       7.7382  | 15.4764  | 22.0515 | -1.61522  |       4.52764 |            0.806561 |               44.8499 |        4.99203 |   5914 |
| position_prior  | TE         |       2.29892 |       9.2325  | 18.465   | 26.615  | -7.20358  |       5.83842 |            0.896517 |               57.6978 |        5.78994 |   5914 |
| quantile_engine | WR         |       3.26122 |      10.2138  | 20.4276  | 29.7767 | -6.34729  |       6.17334 |            0.818672 |               62.5486 |        6.54945 |  11879 |
| rolling_5       | WR         |       3.69693 |      10.8014  | 21.6029  | 30.7081 | -2.20523  |       6.36485 |            0.816735 |               66.0516 |        6.95441 |  11879 |
| position_prior  | WR         |       3.3567  |      13.64    | 27.28    | 37.1927 | -8.59963  |       8.06196 |            0.904117 |               88.4672 |        8.35288 |  11879 |

## Quantile calibration summary

| method          |   mean_absolute_calibration_error |
|:----------------|----------------------------------:|
| position_prior  |                         0.07423   |
| quantile_engine |                         0.0874174 |
| rolling_5       |                         0.115138  |

## Promotion gate

Do not add news, persona, tracking, or deeper sequence models until the quantile engine demonstrates a stable improvement over both baselines across multiple held-out seasons and its intervals are acceptably calibrated by position.
