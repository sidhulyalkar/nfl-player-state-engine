# Agent Operating Guide

This file is the canonical instruction sheet for Claude, Codex, and other coding agents working in this repository.

## Mission

Advance the NFL Player State Engine through measurable, leakage-safe experiments. Prefer a small verified improvement over a large speculative architecture.

Read first:

1. `project_goals.md`
2. `docs/benchmark_real_2020_2025.md`
3. `docs/agent_runbook.md`
4. `docs/continual_learning.md`
5. `docs/intelligence_activation_plan.md`
6. `docs/public_collection.md`
7. `MODEL_CARD.md`

## First commands

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev,dashboard,intelligence]"
pytest
pse smoke-test --work-dir .smoke
```

Do not modify modeling code until tests and the smoke test pass.

## Established benchmark

The real benchmark has already been run. Do not repeat it merely to discover the headline result.

- Data: 2020–2025 official nflverse weekly player statistics and schedules.
- Warm-up: 2020.
- Out-of-sample: 2021–2025.
- Pooled quantile engine: won 6 of 7 targets by mean pinball loss.
- Failure: pooled carries model lost badly because zero-heavy WR rows collapsed QB/RB medians.
- Correction: position-specific carries model achieved 0.5091 mean pinball versus 0.5157 for rolling-5.
- Production v0.4 uses `HybridQuantileModelBundle`, routing carries through position-specific heads.

Inspect `artifacts/reports/benchmark_real/` and `artifacts/reports/conformal_real/` before designing a new experiment.

## v0.5 current assignment

Read `docs/experiment_opportunity_availability_v05.md`, `docs/historical_source_acquisition.md`, `docs/fantasy_decision_framework.md`, and `docs/rookie_team_context.md`. The box-score opportunity residual has already failed its promotion gate. Do not tune it until it wins. Prioritize actual-source coverage, strict cutoff joins, player-ID resolution, league-specific decision regret and calibration.

Run before changes:

```bash
pytest
python scripts/run_frozen_opportunity_ablation.py
pse smoke-test --work-dir .smoke
```

When networked historical files are present, run `python scripts/run_historical_source_ablation.py`. Report source coverage before predictive metrics. A gain from a low-coverage inner join is invalid.

## Current priority order

1. Benchmark the implemented opportunity heads against the direct hybrid engine using real snap/route data.
2. Evaluate official evidence families one at a time.
3. Evaluate structured news only beyond objective opportunity and availability.
4. Evaluate public context only as a capped residual/uncertainty modifier.
5. Promote nothing unless shuffled-player and shifted-time controls behave as expected.
6. Explore sequence, graph, and tracking models only after these gates are stable.

## Required inspection

For each experiment, report:

1. Mean pinball and q50 MAE versus the strongest baseline.
2. Empirical q10, q50, and q90 rates.
3. q10-to-q90 coverage and width.
4. Results by eligible position.
5. Results by held-out season.
6. Bias and largest residual cohorts.
7. Whether the gain survives multiple folds and negative controls.

## Coding rules

- Use only information available before the prediction timestamp.
- Keep raw input immutable and checksummed.
- Use the explicit pregame feature allowlist. Never revert to “all columns except target.”
- Add tests for every leakage-sensitive transformation.
- Save predictions before computing aggregate metrics.
- Preserve player, season, week, game, method, source, and cutoff metadata.
- Prefer typed, composable modules over notebook-only code.
- Keep network connectors optional and credentials in environment variables.
- Never add login bypass, cookie harvesting, CAPTCHA evasion, stealth/proxy rotation, private endpoint reverse engineering, or private-account collection.
- Public browser collection must start with an empty profile and fail closed on login or challenge pages.
- Do not infer sensitive traits, diagnoses, or private psychology from public content.
- Do not activate an intelligence feature without a frozen point-in-time ablation.
- Do not automate real-money wagering.

## Reproducing the real benchmark

```bash
python scripts/run_real_benchmark.py
```

Exact source hashes and output artifacts live in `artifacts/reports/benchmark_real/`.

## Continual learning workflow

```bash
python scripts/weekly_refresh.py --config configs/base.yaml
pse learning-status --registry artifacts/models/registry.json
```

Automatic promotion is disabled. Review approved candidates, then promote manually:

```bash
pse promote-model MODEL_ID --registry artifacts/models/registry.json
```

## Experiment format

Every material experiment should create:

```text
artifacts/experiments/<experiment_id>/
├── config.yaml
├── manifest.json
├── predictions.parquet
├── summary_metrics.csv
├── season_metrics.csv
├── position_metrics.csv
├── calibration.csv
├── notes.md
└── git_commit.txt
```

The notes must state hypothesis, train/test windows, cutoff, feature family, baseline, primary metric, calibration result, negative controls, failure analysis, and decision: reject, revise, or promote.

## Intelligence promotion gate

Before adding any intelligence family to production:

1. Freeze the numerical predictions and folds.
2. Build source snapshots with authored and collected timestamps.
3. Join with the configured safety lag.
4. Add one family at a time.
5. Re-run identical folds.
6. Compare season and position deltas.
7. Run shuffled-player and shifted-time controls.
8. Reject the family if the gain is unstable, uncalibrated, or explained by leakage.

## Definition of done for the next agent cycle

- A preregistered conformal-calibration experiment is complete.
- Passing-yard undercoverage and target/reception overcoverage are quantified by position and season.
- At least one objective opportunity feature family is integrated and ablated.
- Continual-learning registry behavior is tested on a synthetic new week.
- No social/persona feature is promoted yet.

## v0.6 product-agent workflow

When working on the fantasy product layer:

1. Read `docs/product/current_package_state.md`, `product_vision.md`, and `requirements.md`.
2. Keep the Python Product API authoritative for projections and optimization.
3. Never move model math into Gemini prompts or browser code.
4. Normalize every platform into `LeagueSnapshot` and add fixture-driven tests.
5. Test league imports for scoring, slots, ownership, free agents, and player-ID coverage.
6. Evaluate trade changes on both complete post-trade rosters and legal lineups.
7. Add new UI views to `apps/gemini-fantasy-console` without removing demo mode.
8. Make data freshness, uncertainty, and missing inputs visible.
9. Update `docs/product/testing_predictive_capability.md` when adding a decision metric.
10. Do not claim product or predictive performance from synthetic frontend fixtures.
