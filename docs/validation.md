# Validation Status

Validated on July 27, 2026:

- 26 unit tests passed.
- Python source, tests, and scripts compiled successfully.
- The synthetic end-to-end smoke workflow completed with the v0.3 hybrid bundle:
  - raw synthetic player stats and schedules;
  - leakage-safe weekly feature construction;
  - temporal holdout training;
  - future-week slate generation;
  - multi-target q10/q50/q90 prediction;
  - position-specific carries routing;
  - correlated Monte Carlo simulation.
- Static and rendered public-page extraction helpers passed access-boundary tests.
- Continual-learning promotion gates and model registry passed unit tests.
- The official 2020–2025 nflverse benchmark completed on 34,883 regular-season QB/RB/WR/TE player-weeks.
- Source file sizes and SHA-256 hashes are archived in `artifacts/reports/benchmark_real/DATA_MANIFEST.json`.
- The pooled engine beat the strongest baseline on six of seven targets; the carries failure was reproduced, diagnosed, and corrected with position-specific heads.

The live public-browser collector was not exercised against third-party social platforms because it requires current page access, robots permission, optional Playwright installation, and source-by-source review. Its extraction, access-wall detection, URL safety, and private-network blocking are unit tested.

GitHub Actions continual refresh is a scaffold. It should be connected to durable object storage before being treated as a production registry.

## v0.4 validation

- 34 unit tests pass.
- Python source and scripts compile.
- Original synthetic ingest → feature → train → slate → predict → simulate smoke test passes.
- Opportunity-head synthetic three-season train/holdout smoke test passes.
- Frozen 2021–2025 real predictions were recalibrated season by season with no same-season residual use.
- Passing-yard interval coverage moved from 71.73% to 81.04%.
- Target interval coverage moved from 90.17% to 83.73% while pinball improved 0.61%.
- Receptions remain discrete/zero-inflated and conservative; this is documented rather than marked solved.
- Public network collectors were not invoked in validation because credentials and live-source permissions vary.
- Ruff was not available in the packaging runtime; tests and byte-compilation were used as executable checks.
