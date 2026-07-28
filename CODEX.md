# Codex Instructions

Use `AGENTS.md` for repository-wide rules.

Primary task order:

1. establish a clean environment;
2. run tests and smoke test;
3. inspect the completed 2020–2025 benchmark;
4. select one calibration or opportunity bottleneck;
5. preregister the experiment;
6. implement the smallest justified change with leakage tests;
7. archive out-of-sample predictions and subgroup metrics;
8. update the model registry only after gates pass.

Do not rerun the full benchmark without recording source hashes. Do not introduce login bypass, cookie/session reuse, CAPTCHA evasion, stealth/proxy rotation, private endpoint scraping, automated wagering, or post-cutoff information. Public browser collection is limited to content served to a clean unauthenticated browser and must fail closed on access challenges.

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

Before modifying frontend or API code, run `PYTHONPATH=src pytest -q`. Keep API response contracts in `product/schemas.py`. Add deterministic tests for league import, ownership, lineup legality, trade symmetry, and NFL state. Treat Gemini as an explanation/tool-selection layer only.
