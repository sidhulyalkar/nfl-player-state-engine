# BDB27 Milestone 3: preregistered-style evaluation template (research only)

**Status:** software-qualified with synthetic fixtures; **NOT preregistered**, independently audited, run on licensed 2027 files, or validated as a football finding. The template must be edited and frozen *before* examining the held-out outcomes. The existing 2025 cohort may already have influenced previous public analyses, so even a frozen local experiment is exploratory until independently replicated.

**Authority:** `RESEARCH_ONLY_NO_PROMOTION`. Do not promote candidate features into fantasy projections, publish player-level licensed derivative data, claim measured gaze/attention/awareness, infer left/right plant force or injury risk, or pretend that tracking geometry determines a player's cognitive decision.

## Primary, falsifiable hypothesis

For one *declared* position/drill and one independently reviewed **rookie regular-season event-rate endpoint**, adding absolute directional speed-retention asymmetry to (a) conventional Combine and (b) basic Combine tracking features reduces **held-out opportunity-capped weighted MAE**. Signed left/right labels are not cross-domain qualified until official source coordinate semantics are verified, so `abs_asymmetry_pct` is the only supported directional candidate. It is a path-turn asymmetry, not side-specific tissue strain.

Do **not** choose the drill, endpoint, feature family, eligibility cutoff, alpha, or exclusion thresholds by looking at 2025 outcomes. Inspect only training years and measurement coverage before committing the exact design. The example template contains **placeholders** rather than inventing competition column names or a validated coverage metric.

## Inputs and source contract

1. Original, locally authorized `players.csv`, `combine_results.csv`, `combine_tracking.csv` from the 2027 Kaggle source. Official schema, licensing, and `Y` axis semantics must be manually qualified. Exact `players.csv` and `combine_tracking.csv` SHA-256 must match the v2 qualified Combine manifest.
2. The v2 private Combine audit directory: `qualification_manifest.json`, `turn_events_RESEARCH_ONLY.csv`, `asymmetry_RESEARCH_ONLY.csv`. It must have been generated from the same player registry.
3. An independently curated, **role-appropriate** `rookie_outcomes.csv` with exactly one row per `(player_id, position, season, outcome_name)`. Mandatory fields: `player_id, position, season, outcome_name, numerator, denominator, season_type`. `season_type=REG`, `season=draft_year`, numerator and denominator are nonnegative integer counts with `numerator <= denominator`. All exposures must have **verified event semantics and source provenance**, ideally derived from player-play records joined to `games.csv` and unique opportunity identifiers. This pipeline does *not* invent those event labels or infer numerator/denominator from missing values or aliases; a coach/analyst must audit the definition.
4. A frozen JSON study design based on `configs/research/bdb27_prediction_design.template.json`, adjusted to *actual source fields*. The baseline feature list comes only from `combine_results.csv`, never NFL-derived or draft/career columns. Default split is draft cohorts **2023 + 2024 for training; 2025 for holdout**. No player may appear twice in a model comparison.

**Major constraint:** This study analyzes only observed prospect players who have a qualified bilateral profile *and* enough NFL rookie opportunities. A cohort-selection funnel and a broader A/B conventional-versus-basic-tracking comparison are recorded so strong results from a tiny selected subgroup cannot be presented as general scouting gains.

## Evaluation methods

- M0: ridge model using manually named conventional Combine columns.
- M1: M0 plus median entry speed and speed retention, calculated first per *independent physical attempt*, then per player. No single attempt with many detected events dominates.
- M2: M1 plus **absolute** signed path-turn speed-retention asymmetry, estimated from the v2 demand-matched, attempt-block bootstrap only when `status=estimated`.
- M0/M1/M2 use **identical players**, targets, capped opportunity weights, feature-imputation parameters learned from training data only, and fixed ridge alpha; M0/M1 are also reported separately over the broader tracking-observed population.
- Primary difference = M2 minus M1 in opportunity-capped *weighted MAE*. Negative favors M2. The 95% percentile bootstrap resamples **held-out players** (conditional on the training fit), not frames or plays. It is not a full sampling-distribution or model-uncertainty interval.
- Negative control independently permutes only the directional feature within 2023, 2024, and 2025 cohorts, refits M2 and recomputes its held-out error. Retains baseline features, exposures, and player outcomes intact. The one-sided tail fraction is exploratory, not a fully selective/multiple-testing-adjusted p-value.
- Require at least 25 independent train players, 12 holdout players, >=20 outcome opportunities per player, and a qualified asymmetry estimate. If inadequate, output `insufficient_evidence` and **no model comparison or player ranking**.
- No per-player scouting judgments, causal inference, cognitive traits, visual field, neck geometry or physiological load can be established by this study.

## How to run without publishing competition data

```bash
python -m pip install -e '.[dev]'
PYTHONPATH=src:. pytest -q tests/research

# Use the v2 source qualifier first (see bdb27_source_qualification_v2.md).
# Review your target's actual semantics and freeze your exact design before viewing test labels.
python scripts/run_bdb27_frozen_prediction.py \
  --source-dir /secure/bdb27-raw \
  --combine-dir /secure/bdb27-combine-qualified \
  --outcomes /secure/curated-rookie-outcomes.csv \
  --design /secure/bdb27-confirmed-design.json \
  --output-dir /secure/bdb27-prediction-private \
  --acknowledge-competition-data-terms \
  --confirm-outcome-provenance-reviewed
```

All paths are local. Never commit the original data, event/player predictions, metrics for identifiable players, or unlicensed videos. The output directory must be outside the project and original source directory. Input/source SHA-256 and design digest are written to `evaluation_RESEARCH_ONLY.json`; `cohort_eligibility_PRIVATE.csv` retains who was missing and why, and `heldout_player_predictions_PRIVATE.csv` is emitted **only when the eligibility threshold is reached**. Explicit acknowledgments record user declarations, not verified rights or independently reviewed outcomes.

## Gates for an actual scientific claim

1. **G0: Source and labels.** Verify each official file, season, original sample definition, coordinate handedness, timestamp base, drill attempt independence, and label denominator. A conservative terminal report showing low coverage is a valid finding.
2. **G1: Measurement.** Manually annotate both positive and no-turn drills, include multiple reviewers, quantify inter-rater agreement and 10 Hz event uncertainty. Verify asymmetry robustness to 2D source geometry, rotations/reflections, speed/angle bin definitions, missing attempt segments, and athlete-level coverage.
3. **G2: Transfer.** Report paired Combine-to-NFL movement feasibility separately from outcome forecasting. Different task distributions, right/left geometry and unobserved player choices may make the raw sign incomparable.
4. **G3: Outcome.** Validate one position-specific, opportunity-normalized target using verified source evidence. Train on 2023/2024 players; test on 2025 once after freezing choices. Record exclusions and missing opportunity outcomes. No tuning to improve 2025 after examining it.
5. **G4: Decision value.** Compare M0 vs M1 and M1 vs M2, show opportunity and cohort calibration, bootstrap uncertainty, permutation controls, and a football use case. If C does not improve, keep the negative result. Do not equate a low predictive error with situational awareness.
6. **G5: Independent reproduction.** Freeze hashes, dependencies, configs and notebook. Reproduce without reselecting the best drill or endpoint using held-out results. Design a prospective video/eye-tracking study separately if claiming gaze or cognition.

## Current blocker

No authorized 2027 raw CSVs are mounted in this working environment. All new tests are synthetic. Until the actual source dictionary, role-specific outcome semantics, and cohort counts are reviewed, we **cannot** claim directional asymmetry matters for NFL outcomes or compute an honest real-player score. The official competition requires explicit Combine tracking -> regular-season NFL outcome linkage, and a public reproducible Kaggle notebook; that submission evidence remains to be built.
