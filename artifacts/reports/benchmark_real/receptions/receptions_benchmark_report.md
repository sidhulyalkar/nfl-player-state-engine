# Multi-season benchmark: `receptions`

All rows are walk-forward out-of-sample predictions. Lower MAE, RMSE, pinball loss, and calibration error are better.

## Overall comparison

| method          |   pinball_q10 |   pinball_q50 |     mae |    rmse |       bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|--------------:|--------------:|--------:|--------:|-----------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine |      0.223822 |      0.633641 | 1.26728 | 1.7701  | -0.226323  |      0.355161 |            0.905726 |               4.50713 |       0.404208 |  25235 |
| rolling_5       |      0.236713 |      0.656598 | 1.3132  | 1.82456 | -0.0970927 |      0.362205 |            0.825956 |               3.89591 |       0.418505 |  25235 |
| position_prior  |      0.224232 |      0.838776 | 1.67755 | 2.32536 | -0.53723   |      0.486883 |            0.923915 |               5.42932 |       0.51663  |  25235 |

## Position-specific comparison

| method          | position   |   pinball_q10 |   pinball_q50 |     mae |    rmse |        bias |   pinball_q90 |   interval_coverage |   mean_interval_width |   mean_pinball |   rows |
|:----------------|:-----------|--------------:|--------------:|--------:|--------:|------------:|--------------:|--------------------:|----------------------:|---------------:|-------:|
| quantile_engine | RB         |      0.159904 |      0.554403 | 1.10881 | 1.56165 | -0.202938   |      0.322312 |            0.916555 |               3.75536 |       0.34554  |   7442 |
| rolling_5       | RB         |      0.193964 |      0.572324 | 1.14465 | 1.61623 | -0.135967   |      0.327582 |            0.825047 |               3.28369 |       0.364623 |   7442 |
| position_prior  | RB         |      0.15993  |      0.666622 | 1.33324 | 1.92879 | -0.599301   |      0.408037 |            0.917764 |               4.01332 |       0.41153  |   7442 |
| quantile_engine | TE         |      0.221695 |      0.600202 | 1.2004  | 1.69041 | -0.264535   |      0.336921 |            0.908184 |               4.42518 |       0.386273 |   5914 |
| rolling_5       | TE         |      0.232298 |      0.631709 | 1.26342 | 1.73161 |  0.00717225 |      0.346532 |            0.82533  |               3.66893 |       0.403513 |   5914 |
| position_prior  | TE         |      0.221914 |      0.793033 | 1.58607 | 2.14435 | -0.219141   |      0.470172 |            0.915962 |               5       |       0.49504  |   5914 |
| quantile_engine | WR         |      0.264923 |      0.699931 | 1.39986 | 1.925   | -0.221949   |      0.38482  |            0.897719 |               5.01891 |       0.449891 |  11879 |
| rolling_5       | WR         |      0.265693 |      0.721786 | 1.44357 | 1.98561 | -0.124647   |      0.391697 |            0.826837 |               4.39245 |       0.459725 |  11879 |
| position_prior  | WR         |      0.265671 |      0.9694   | 1.9388  | 2.62049 | -0.656705   |      0.544598 |            0.931728 |               6.53016 |       0.593223 |  11879 |

## Quantile calibration summary

| method          |   mean_absolute_calibration_error |
|:----------------|----------------------------------:|
| quantile_engine |                         0.0763756 |
| position_prior  |                         0.0970576 |
| rolling_5       |                         0.107247  |

## Promotion gate

Do not add news, persona, tracking, or deeper sequence models until the quantile engine demonstrates a stable improvement over both baselines across multiple held-out seasons and its intervals are acceptably calibrated by position.
