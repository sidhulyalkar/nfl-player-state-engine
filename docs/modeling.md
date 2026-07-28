# Modeling Notes

## Hierarchical decomposition

The intended mature model decomposes output into:

```text
team play volume
× player participation
× opportunity share
× conditional efficiency
```

v0.1 predicts final outcomes directly while exposing the component targets needed for later decomposition: passing attempts, carries, targets, receptions, and yardage.

## Current estimator

Each target/quantile pair uses a scikit-learn histogram gradient boosting regressor behind numeric/categorical preprocessing. Independent quantile predictions are sorted to prevent crossing.

## Candidate upgrades

An upgrade must beat the temporal baseline on calibration and proper scoring rules, not only MAE.

- CatBoost quantile regression
- Conformalized quantile regression
- Hierarchical Bayesian player and team states
- Zero-inflated count models for opportunities
- Distributional boosting or mixture-density heads
- Multi-task opportunity/efficiency architecture
- Play-sequence transformer or state-space model
- Graph model for player matchups
- Tracking trajectory encoder

## Cold-start strategy

Rookies, role changes, trades, and injury returns require partial pooling. Candidate priors include position, draft capital, depth-chart role, team system, combine traits, and comparable-player embeddings. They should be evaluated as separate cold-start cohorts.
