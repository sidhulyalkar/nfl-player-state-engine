# Evidence Factory

## Purpose

The Evidence Factory is the canonical frozen comparison layer for NFL Player State Engine model research.

Its job is not to create a new forecasting model. Its job is to make every model family answer the same questions on the same held-out player-weeks:

- what did the model know at forecast time;
- what q10/q50/q90 distribution did it publish;
- what actually happened;
- which production model is authoritative for this target;
- how did the challenger compare with that target's champion;
- was any apparent improvement stable by season, position, and week;
- did calibration and sharpness remain acceptable;
- was sufficient evaluable data actually paired;
- does the player-specific mapping beat an identity-destroyed negative control;
- does the result survive family-wise multiple-testing control;
- what evidence is still missing before promotion can even be considered.

Production authority is target-aware. The current direct stack uses `quantile_engine` for the ordinary pooled targets and `position_specific_quantile` for carries because `HybridQuantileModelBundle` routes carries through position-specific heads. Evidence Factory output is always `research_evidence_only`.

## Canonical prediction contract

Every frozen row is normalized to:

```text
forecast_id
target
method
source
player_id
season
week
position
prediction_cutoff
actual
q10
q50
q90
valid_outcome
valid_quantiles
valid_prediction
crossed_quantiles
```

The unique identity is:

```text
target + method + player_id + season + week
```

Duplicate identities fail closed. This is deliberate. A duplicate row can turn a paired join into a many-to-many join and manufacture apparent statistical evidence.

`player_id`, `season`, `week`, `target`, and `method` are identity fields. Missing player IDs, blank methods, non-finite seasons/weeks, and non-integer seasons/weeks fail closed instead of being silently coerced into new identities.

Forecast-value missingness behaves differently. A row with a realized outcome but a missing/non-finite quantile remains in the canonical artifact with `valid_prediction=false`. This preserves the denominator needed to measure challenger data availability instead of hiding difficult rows by dropping them.

Paired artifacts must also agree on the realized outcome and, when both know it, the player's position.

## Metrics

The factory calculates the same distribution diagnostics for every model:

- q10 pinball loss;
- q50 pinball loss;
- q90 pinball loss;
- mean pinball loss;
- q50 MAE;
- q50 signed bias;
- empirical q10-q90 coverage;
- coverage gap from the nominal 80% target;
- mean q10-q90 interval width;
- crossed-quantile rate;
- valid-prediction rate against evaluable outcomes;
- prediction-cutoff availability.

The same metrics are emitted for:

- overall;
- season;
- position;
- position x season;
- season x week.

Coverage and interval width must be read together. A model does not become better merely by making its intervals enormous.

## Target-aware champions

Evidence Factory does not assume that one implementation is authoritative for every target.

The default champion is:

```text
quantile_engine
```

The current built-in override is:

```text
carries=position_specific_quantile
```

This matches the production `HybridQuantileModelBundle`, which uses position-specific heads for carries while retaining the pooled direct quantile implementation for the other supported targets.

The override exists because the historical benchmark intentionally preserved the old pooled carry engine and later wrote the position-specific correction as a separate artifact. Evidence Factory keeps both pieces of history without incorrectly calling the obsolete pooled carry implementation the current champion.

Additional explicit overrides can be supplied with repeated CLI arguments:

```bash
python scripts/run_evidence_factory.py \
  --champion-override carries=position_specific_quantile \
  --champion-override targets=some_future_target_champion
```

The resolved map is written to `run_manifest.json` as `champion_methods` and displayed in Model Observatory.

## Paired comparisons

For each target, every challenger is compared against that target's configured champion on identical frozen rows.

The primary effect is:

```text
champion mean pinball - challenger mean pinball
```

Positive values favor the challenger.

Uncertainty is estimated with the existing paired season/week block bootstrap. Blocks are sampled as sums and counts so the bootstrap targets the same row-weighted estimand as the headline effect.

Every comparison reports:

- paired rows and seasons;
- overlap rate among rows where both models produced valid distributions;
- paired data availability against the union of evaluable player-week outcomes;
- champion and challenger mean pinball;
- paired effect and confidence interval;
- bootstrap probability of improvement;
- finite-sample one-sided bootstrap p-value;
- Benjamini-Hochberg FDR q-value;
- q50 MAE;
- 80% interval coverage;
- interval width;
- crossed-quantile rate;
- season consistency;
- position consistency;
- week consistency;
- evidence tier;
- promotion blockers.

Paired data availability is deliberately stricter than overlap. If a challenger has predictions for only five of eight evaluable outcomes, a perfect five-of-five overlap with the champion does not become 100% availability. The comparison records 5/8 availability and the promotion policy can block it.

## Identity-permutation negative control

Every challenger is also tested against an identity-destroyed version of itself.

Within each `season x position` slice, the challenger keeps the same q10/q50/q90 triplets and therefore the same coarse forecast marginals and interval geometry. The triplets are cyclically reassigned to different player-weeks using a deterministic seeded non-zero shift whenever the slice contains at least two rows.

The test therefore asks whether the model's player-specific mapping contains real predictive information beyond its coarse positional and seasonal distribution.

The negative-control effect is:

```text
identity-permuted control pinball - real challenger pinball
```

The control passes only when:

```text
effect > 0
and paired 95% confidence interval lower bound > 0
```

Singleton groups cannot be permuted and are reported explicitly. A failed or uninformative identity control remains a promotion blocker.

This is a signal/leakage sanity check, not proof that every possible leakage channel has been excluded.

## Multiple testing

Evidence Factory treats all challenger-vs-target-champion comparisons in a run as one multiple-testing family.

The paired bootstrap first measures the fraction of resampled effects that do not favor the challenger. When `B` bootstrap draws are available, the publication p-value uses a finite-sample plus-one tail estimate:

```text
p = (unfavorable bootstrap draws + 1) / (B + 1)
```

This prevents a finite bootstrap run from publishing an exact `p=0` simply because every sampled effect happened to land on the favorable side.

The complete run then applies Benjamini-Hochberg correction across all target/challenger comparisons and writes the run-wide FDR q-value back into both:

```text
paired_comparisons.csv
experiment_ledger.csv
```

Target-local q-values are overwritten in the final publication bundle. A regression test explicitly covers the case where locally acceptable comparisons become blocked once the complete run-wide family is corrected.

The current promotion policy uses `maximum_fdr_q=0.10`. Missing, invalid, non-finite or above-threshold run-wide FDR evidence fails closed.

FDR correction does not turn a historical comparison into production authority. It only closes one statistical loophole in a larger evidence policy.

## Promotion remains fail closed

A good paired result is not model promotion.

The Evidence Factory reuses `state_graph.experiments.PromotionPolicy`. A normal multi-season historical comparison is at most `MULTI_SEASON_ISOLATED` until downstream decision evidence exists.

The current production gate still requires, where applicable:

- sufficient evidence tier;
- positive useful effect;
- confidence interval clearing the gate;
- season consistency;
- position consistency;
- week consistency;
- sufficient paired coverage;
- sufficient evaluable data availability;
- negative controls;
- downstream fantasy decision evidence;
- acceptable run-wide FDR evidence.

Evidence Factory additionally blocks challengers whose 80% interval coverage is outside the configured tolerance or whose quantiles cross.

## Player State Graph scoring guard

The Player State Graph samples football statistics and then applies an exact league scoring contract. Therefore its fantasy-point output must not be compared with a PPR champion merely because both columns are called fantasy points.

`run_evidence_factory.py` reads the graph `run_manifest.json` and only ingests graph fantasy summaries when both are true:

```text
base scoring weights == canonical PPR weights
tight_end_premium == 0.0
```

A scoring mismatch is recorded in the Evidence Factory manifest and the graph is excluded from the paired fantasy comparison.

## Run it

First reproduce the frozen nflverse benchmark if needed:

```bash
python scripts/run_real_benchmark.py \
  --reuse-features \
  --output-dir artifacts/reports/benchmark_real
```

Generate Player State Graph artifacts separately if you want the graph included as a challenger:

```bash
python scripts/run_player_state_graph_research.py \
  --history data/processed/player_week_history.parquet \
  --forecast-rows data/processed/forecast_rows.parquet \
  --league-config configs/fantasy/8_team_ppr_2qb_expanded.yaml \
  --champion-predictions artifacts/reports/benchmark_real/fantasy_points_ppr/fantasy_points_ppr_predictions.csv \
  --output-dir artifacts/player_state_graph
```

Then build the evidence ledger:

```bash
python scripts/run_evidence_factory.py \
  --benchmark-root artifacts/reports/benchmark_real \
  --graph-root artifacts/player_state_graph \
  --output-dir artifacts/evidence_factory
```

To restrict the run:

```bash
python scripts/run_evidence_factory.py \
  --targets fantasy_points_ppr targets carries \
  --bootstrap-samples 5000
```

## Output contract

```text
artifacts/evidence_factory/
  canonical_predictions.parquet
  method_summary.csv
  slice_metrics.csv
  paired_comparisons.csv
  experiment_ledger.csv
  negative_controls.csv
  run_manifest.json
  report.md
```

`run_manifest.json` stores:

- schema version;
- creation timestamp;
- Git SHA when available;
- default champion method;
- resolved target-to-champion map;
- targets;
- bootstrap settings;
- calibration tolerance;
- multiple-testing family, finite-sample p-value rule and FDR rule;
- negative-control definition and pass rule;
- every input path, byte count, and SHA-256;
- graph scoring-comparability status;
- every output path, byte count, and SHA-256 except the manifest itself;
- explicit non-automatic-promotion authority.

This is the reproducibility anchor. Do not publish benchmark claims without the manifest that produced them.

## Product API

When artifacts are mounted, the operational API exposes:

```text
GET /v1/model/evidence-factory
GET /v1/model/evidence-factory?target=fantasy_points_ppr
```

The response is read-only and includes:

- artifact health;
- run manifest;
- method summary;
- slice metrics;
- paired comparisons;
- experiment ledger;
- negative-control results;
- resolved target-aware production authority;
- explicit research-only authority.

When the artifacts are missing, the endpoint returns `UNAVAILABLE` instead of fabricating placeholder model results.

## Model Observatory

The React Model Observatory reads the same read-only API. Its Evidence Factory panel shows:

- method and challenger counts;
- best paired effect;
- identity-control pass count;
- target champion count;
- artifact health;
- exact run Git SHA;
- graph scoring guard status;
- challenger and actual target champion;
- paired effect and confidence interval;
- Benjamini-Hochberg q-value;
- paired data availability;
- calibration and sharpness;
- identity-control pass/fail;
- promotion blockers.

The UI cannot promote a model or substitute browser-side calculations for the Python evidence ledger.

## CI artifact smoke

The ordinary repository CI runs the Evidence Factory against the checked-in frozen `fantasy_points_ppr` and `carries` benchmark artifacts with a small bootstrap count. The smoke asserts that:

- the artifact pipeline completes on real stored benchmark schemas;
- fantasy points resolves to `quantile_engine`;
- carries resolves to `position_specific_quantile`;
- all comparisons receive finite, non-zero p-values and FDR q-values;
- the manifest remains research-only and non-automatic.

This is a schema/reproducibility guard, not a new benchmark run and not evidence of model promotion.

## Recommended next evidence phase

The next meaningful evidence program should preserve the historical program rather than cherry-picking a favorable slice:

1. rebuild the 2021-2025 point-in-time weekly feature history from frozen source manifests;
2. reproduce the target-aware direct production stack on exactly those player-weeks;
3. retain rolling and position-prior baselines for every supported target;
4. preserve the old pooled carries run as historical evidence while treating the position-specific carry head as current champion;
5. generate Player State Graph forecasts on the exact same eligible player-weeks;
6. inspect overall, season, position, position-season, and week slices;
7. inspect coverage, width, availability, FDR, and negative controls before reading headline loss;
8. only after isolated evidence is credible, move to draft/lineup/waiver/trade decision replay;
9. only after downstream evidence is credible, begin a live shadow-season evidence tier.

The objective is not to make the newest model win. The objective is to make it difficult for a weak model to look strong by accident.
