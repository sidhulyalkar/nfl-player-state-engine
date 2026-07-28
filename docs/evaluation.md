# Evaluation Protocol

## Forecast timestamp

Every production prediction should record:

- Generation time in UTC
- Source-data cutoff
- Injury/depth-chart snapshot time
- Market snapshot time, when applicable
- Model artifact hash
- Feature manifest hash

## Primary metrics

- Mean pinball loss
- Median MAE and RMSE
- Prediction-interval coverage
- Interval width
- Calibration by position and workload tier
- Continuous ranked probability score when a richer density is available

## Market research metrics

- No-vig probability edge
- Expected value at captured price
- Closing-line value
- Profit after vig
- Maximum drawdown
- Bootstrap intervals clustered by game and week

Win rate alone is not acceptable evidence. Player props within a game are correlated, and one season is a small sample.

## Required slices

- Position
- Rookie versus veteran
- Returning from absence
- Home versus away
- Favorite versus underdog
- Indoor versus outdoor
- Early versus late season
- High versus low projected volume
- Stable versus recently changed role
