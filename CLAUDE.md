# Claude Instructions

Follow `AGENTS.md` as the source of truth.

At session start:

1. Read `project_goals.md`, `docs/benchmark_real_2020_2025.md`, and `docs/agent_runbook.md`.
2. Run `pytest` and `pse smoke-test --work-dir .smoke`.
3. Inspect existing benchmark and experiment artifacts before proposing architecture changes.
4. State the active hypothesis, frozen baseline, prediction cutoff, and acceptance criteria in the experiment note.

Current priorities are calibration, objective opportunity decomposition, and official availability evidence. The pooled carries failure has already been diagnosed; production now uses position-specific carries heads.

Favor repository edits, tests, manifests, archived predictions, and reproducible commands over prose-only recommendations. Do not promote public-context/persona features before official availability and opportunity ablations. Do not implement login circumvention or automated wagering.

## v0.5 current assignment

Read `docs/experiment_opportunity_availability_v05.md`, `docs/historical_source_acquisition.md`, `docs/fantasy_decision_framework.md`, and `docs/rookie_team_context.md`. The box-score opportunity residual has already failed its promotion gate. Do not tune it until it wins. Prioritize actual-source coverage, strict cutoff joins, player-ID resolution, league-specific decision regret and calibration.

Run before changes:

```bash
pytest
python scripts/run_frozen_opportunity_ablation.py
pse smoke-test --work-dir .smoke
```

When networked historical files are present, run `python scripts/run_historical_source_ablation.py`. Report source coverage before predictive metrics. A gain from a low-coverage inner join is invalid.

## v0.4 note

Before adding deeper models, inspect `docs/calibration_real_2021_2025.md`, `docs/opportunity_engine.md`, and `docs/intelligence_experiments.md`. Opportunity and intelligence modules are implemented but disabled until their real multi-season ablations pass. Continual challengers embed earlier-residual conformal calibrators; do not fit calibration on the evaluation season.

## Product implementation context

The Google AI Studio frontend lives in `apps/gemini-fantasy-console`. Use `ai_studio/BUILD_PROMPT.md` as the visual and functional contract. The React/Node layer orchestrates typed Product API tools; it must not reproduce Python valuation logic. For platform work, implement one canonical importer at a time with saved fixtures and coverage reports.
