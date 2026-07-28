# Agent Runbook: v0.3 benchmark to intelligence activation

## 1. Initialize

```bash
python --version
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,dashboard,intelligence]"
pytest
pse smoke-test --work-dir .smoke
```

Optional public-browser support:

```bash
python -m pip install -e ".[browser]"
playwright install chromium
```

## 2. Read the completed benchmark

Start with:

```text
artifacts/reports/benchmark_real/REAL_BENCHMARK_REPORT.md
docs/benchmark_real_2020_2025.md
artifacts/reports/benchmark_real/benchmark_engine_vs_best_baseline.csv
artifacts/reports/benchmark_real/benchmark_position_wins.csv
```

Do not treat the pooled carries result as the production architecture. The benchmark exposed the failure; v0.3 corrects production training with position-specific carries heads.

## 3. Reproduce only when needed

```bash
python scripts/run_real_benchmark.py
```

Audit the regenerated `DATA_MANIFEST.json`. If hashes differ, record the source refresh and do not compare metrics as though the data were identical.

## 4. Inspect calibration

For every target and position:

- empirical q10, q50, and q90 rates;
- q10-to-q90 coverage;
- mean interval width;
- median bias;
- season stability;
- row count.

Current highest-priority problems:

- passing yards undercoverage;
- targets and receptions overcoverage;
- position-dependent fantasy intervals.

## 5. Preregister the next experiment

Create `artifacts/experiments/<id>/notes.md` before coding. Specify:

- target and positions;
- exact folds;
- feature cutoff;
- baseline artifact;
- primary metric;
- maximum tolerated subgroup regression;
- calibration and sharpness criteria;
- negative controls.

## 6. Recommended experiment A: conformal calibration

Use out-of-fold residuals from prior seasons only. Fit adjustments separately by target and position, with fallback shrinkage to target-wide calibration when rows are sparse.

Acceptance criteria:

- coverage closer to 80%;
- no material mean-pinball regression;
- interval-width increase justified by coverage correction;
- improvement in at least three held-out seasons.

## 7. Recommended experiment B: opportunity decomposition

Predict in causal order:

```text
active probability
  -> snap share / route share
  -> team play volume
  -> carries / targets
  -> receptions / yards
  -> touchdowns / fantasy points
```

First objective sources:

- weekly rosters and depth charts;
- snap counts;
- participation and formation data;
- official game status and practice participation;
- transactions and quarterback changes.

## 8. Intelligence dry run

```bash
pse build-availability \
  --evidence examples/availability_evidence_template.csv \
  --output .smoke/availability_features.parquet
```

Verify the point-in-time join before live collection. Then test official evidence only. News follows. Public-context/persona features come last.

## 9. Public collection

Use `public_web` for static pages and `public_browser` for JavaScript-rendered pages that are actually available to a clean unauthenticated browser. Collection must stop on login, CAPTCHA, or challenge pages.

```bash
pse collect-intelligence \
  --registry examples/player_sources_template.csv \
  --platform public_browser \
  --output data/external/intelligence/documents.jsonl
```

## 10. Continual update

```bash
python scripts/weekly_refresh.py --config configs/base.yaml
pse learning-status --registry artifacts/models/registry.json
```

Review candidate benchmark artifacts. Promotion remains manual.

## 11. Error taxonomy

Maintain examples of:

- inactive players projected active;
- rookie and return-from-injury cold starts;
- abrupt role changes;
- trades and team changes;
- quarterback changes;
- committee backfields;
- extreme game scripts;
- touchdown-driven tails;
- weather outliers;
- source or join anomalies.

## v0.4 note

Before adding deeper models, inspect `docs/calibration_real_2021_2025.md`, `docs/opportunity_engine.md`, and `docs/intelligence_experiments.md`. Opportunity and intelligence modules are implemented but disabled until their real multi-season ablations pass. Continual challengers embed earlier-residual conformal calibrators; do not fit calibration on the evaluation season.

## Product-layer iteration

```bash
python -m pip install -e ".[dev,api]"
PYTHONPATH=src pytest -q
pse serve-product-api
```

For frontend development:

```bash
cd apps/gemini-fantasy-console
npm install
npm run dev
```

Before declaring an integration complete, save anonymized fixtures, test canonical normalization, report unresolved player IDs, and verify that the complete league ownership count matches the source platform.
