# Continual learning and model promotion

## What “continual” means here

The engine uses **guarded continual batch learning**, not uncontrolled online gradient updates.

After a newly completed week arrives:

1. Refresh official source data.
2. Rebuild all point-in-time features from immutable history.
3. Detect whether the model registry has already seen the newest completed week.
4. Train an expanding-window challenger.
5. Re-run temporal baseline and calibration checks.
6. Register the challenger as approved or rejected.
7. Require manual champion promotion by default.

This design is slower than blindly calling `partial_fit`, but much safer for a domain with stat corrections, player turnover, coaching changes, and a tiny number of weekly observations.

## Current status

v0.2 did **not** learn automatically. It supported manual batch training and backtesting.

v0.3 adds:

- `pse continual-update`
- `pse learning-status`
- `pse promote-model`
- `ModelRegistry` with challenger, approved, rejected, and champion states
- new-week detection
- baseline, calibration, and position-regression gates
- target-aware hybrid training, including position-specific carries heads
- `scripts/weekly_refresh.py`
- `.github/workflows/weekly_model_refresh.yml`

Automatic promotion remains disabled in `configs/base.yaml` and `configs/benchmark_real.yaml`.

## Local update

```bash
python scripts/weekly_refresh.py \
  --config configs/base.yaml \
  --registry artifacts/models/registry.json

pse learning-status --registry artifacts/models/registry.json
```

Review the candidate benchmark report, then promote explicitly:

```bash
pse promote-model MODEL_ID --registry artifacts/models/registry.json
```

## Promotion gates

A candidate can be approved only when:

- its mean pinball improvement meets the configured threshold;
- its q10-to-q90 coverage is sufficiently close to 80%;
- no eligible position regresses beyond the configured tolerance;
- predictions and benchmark artifacts are successfully archived.

Approval is not promotion. Manual review should additionally inspect season stability, bias, interval width, row coverage, and data-source freshness.

## Scheduled workflow

The included GitHub Actions workflow runs Thursday, after the usual weekly stat-correction window, and can also be triggered manually. It restores candidate state from Actions cache, runs tests, refreshes data, trains gated challengers, and uploads review artifacts.

For a production deployment, replace Actions cache with durable object storage and a transactional registry. Cache restoration is a convenient scaffold, not a bank vault.

## Drift monitoring to add

- feature missingness by week and source;
- prediction median and interval-width drift;
- calibration over trailing 4, 8, and 18-week windows;
- error by position, team, rookie status, team change, and injury status;
- source schema and hash changes;
- champion-versus-challenger shadow predictions.

## v0.4 note

Before adding deeper models, inspect `docs/calibration_real_2021_2025.md`, `docs/opportunity_engine.md`, and `docs/intelligence_experiments.md`. Opportunity and intelligence modules are implemented but disabled until their real multi-season ablations pass. Continual challengers embed earlier-residual conformal calibrators; do not fit calibration on the evaluation season.
