# Evidence Factory

## Purpose

The Evidence Factory is the canonical frozen comparison layer for NFL Player State Engine model research.

Its job is not to create a new forecasting model. Its job is to make every model family answer the same questions on the same held-out player-weeks:

- what did the model know at forecast time;
- what q10/q50/q90 distribution did it publish;
- what actually happened;
- how did it compare with the production champion;
- was any apparent improvement stable by season, position, and week;
- did calibration and sharpness remain acceptable;
- does the player-specific mapping beat an identity-destroyed negative control;
- what evidence is still missing before promotion can even be considered.

The direct quantile model remains production-authoritative. Evidence Factory output is `research_evidence_only`.

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
valid_prediction
crossed_quantiles
```

The unique identity is:

```text
target + method + player_id + season + week
```

Duplicate identities fail closed. This is deliberate. A duplicate row can turn a paired join into a many-to-many join and manufacture apparent statistical evidence.

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
- crossed-quantile rate.

The same metrics are emitted for:

- overall;
- season;
- position;
- position x season;
- season x week.

Coverage and interval width must be read together. A model does not become better merely by making its intervals enormous.

## Paired comparisons

The factory compares each challenger against `quantile_engine` on identical frozen rows.

The primary effect is:

```text
champion mean pinball - challenger mean pinball
```

Positive values favor the challenger.

Uncertainty is estimated with the existing paired season/week block bootstrap. Blocks are sampled as sums and counts so the bootstrap targets the same row-weighted estimand as the headline effect.

Every comparison reports:

- paired rows and seasons;
- overlap rate;
- champion and challenger mean pinball;
- paired effect and confidence interval;
- bootstrap probability of improvement;
- q50 MAE;
- 80% interval coverage;
- interval width;
- crossed-quantile rate;
- season consistency;
- position consistency;
- week consistency;
- evidence tier;
- promotion blockers.

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
- sufficient paired/data availability;
- negative controls;
- downstream fantasy decision evidence;
- valid FDR evidence when multiple hypothesis testing is used.

Evidence Factory also blocks challengers whose 80% interval coverage is outside the configured tolerance or whose quantiles cross.

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
  --league-config config/leagues/ppr.yaml \
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

- creation timestamp;
- Git SHA when available;
- production champion method;
- targets;
- bootstrap settings;
- calibration tolerance;
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
- explicit research-only authority.

When the artifacts are missing, the endpoint returns `UNAVAILABLE` instead of fabricating placeholder model results.

## Model Observatory

The React Model Observatory reads the same read-only API. Its Evidence Factory panel shows:

- method and challenger counts;
- best paired effect;
- identity-control pass count;
- promotion-eligible count;
- artifact health;
- exact run Git SHA;
- graph scoring guard status;
- paired effect, confidence interval, calibration, sharpness and promotion blockers for each mounted challenger.

The UI cannot promote a model or substitute browser-side calculations for the Python evidence ledger.

## Recommended first real run

The first meaningful Evidence Factory run should preserve the existing historical program rather than cherry-picking a favorable slice:

1. acquire/rebuild the 2021-2025 point-in-time weekly feature history;
2. retain the current production quantile engine as champion;
3. compare rolling and position-prior baselines for every supported target;
4. preserve the position-specific carries correction as its own method;
5. generate graph forecasts on the exact same eligible player-weeks;
6. inspect overall, season, position, position-season, and week slices;
7. inspect coverage and width before reading headline loss;
8. require the player-specific forecast to beat its identity-permuted control;
9. only after isolated evidence is credible, move to draft/lineup/waiver/trade decision replay.

The objective is not to make the newest model win. The objective is to make it difficult for a weak model to look strong by accident.
