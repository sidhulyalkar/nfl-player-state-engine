# Carries model correction

The frozen pooled benchmark exposed a structural zero-inflation failure. WR rows dominated the shared conditional median, causing near-zero QB/RB carry projections.

| Method | MAE | Mean pinball | 80% coverage | Width |
|---|---:|---:|---:|---:|
| Pooled quantile engine | 3.1442 | 0.7844 | 0.9200 | 5.8161 |
| Rolling-5 baseline | 1.5783 | 0.5157 | 0.8265 | 4.7613 |
| Position-specific quantile | 1.5173 | 0.5091 | 0.9067 | 5.8203 |

The position-specific model improves mean pinball by 1.29% and MAE by 3.87% versus rolling-5. v0.3 integrates this strategy in `HybridQuantileModelBundle`.

The original pooled prediction archive remains untouched as the diagnostic evidence that motivated the architecture change.
