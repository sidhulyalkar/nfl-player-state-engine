# Historical Official Availability v2

## Purpose

This experiment asks a narrow modelling question:

> Does point-in-time official NFL availability evidence add out-of-sample predictive value for weekly PPR fantasy outcomes beyond the numerical player-state baseline?

The experiment is intentionally narrower than the complete structured-intelligence roadmap. It begins with archived official injury reports only. Depth-chart, news, public-persona, and broader contextual evidence remain separate evidence families and are not allowed to borrow authority from this result.

## Why this is v2

The earlier July benchmark was content-addressed, but its raw schedule bytes were not retained. A later archival recovery attempt could verify the contemporaneous player-stat hashes, but the exact schedule SHA could not be recovered from a bounded search of `nfldata` Git history. That experiment is therefore **archivally blocked**. It is not a failed model experiment and its provenance must not be reconstructed approximately.

v2 creates a new research identity instead:

- every numerical source has an exact byte count and SHA-256;
- schedules come from one pinned `nfldata` commit;
- every historical injury source has an exact byte count and SHA-256;
- the aggregate numerical and injury identities are registered in Git;
- the raw input bundle is retained as a GitHub Actions artifact while artifact retention permits;
- the experiment never claims byte-for-byte historical production feature parity.

The canonical registry is `experiments/historical_official_availability_v2/registered_inputs.json`.

## Primary scope: regular season

The primary fantasy use case is the NFL regular season, so the registered confirmatory analysis evaluates `season_type == REG` for seasons 2020-2024.

The weekly feature builder still sees the complete chronological source before the evaluation table is restricted to REG. This matters around season boundaries: a postseason game that is chronologically prior to the next regular season may legitimately inform lagged player-state history. Postseason rows themselves are not fitted or scored as targets in the primary experiment.

An earlier all-games diagnostic was retired after two issues were identified:

1. postseason source-coverage behavior was materially different from the regular-season fantasy use case;
2. the historical adapter did not yet recognize nflverse's long-form practice strings.

No statistical conclusion from that superseded diagnostic is authoritative.

## Historical injury semantics

The frozen nflverse releases use these practice-status values directly:

- `Full Participation in Practice`
- `Limited Participation in Practice`
- `Did Not Participate in Practice`

The canonical historical adapter maps them to `full`, `limited`, and `did_not_participate` respectively. Regression tests protect those exact source strings.

Official evidence is selected only when its archived `date_modified` is at or before the player-game prediction cutoff. The registered cutoff is 1.5 hours before kickoff. Later injury-report revisions are not permitted to rewrite an earlier prediction state.

Source coverage and evidence prevalence are deliberately distinct:

- **source coverage** asks whether the team's official injury-report source was demonstrably observable before the cutoff;
- **evidence prevalence** asks whether that player actually had an applicable report row before the cutoff.

A player absent from an observed team report is therefore not conflated with a player-week for which the source itself was unavailable.

## Numerical baseline

The registered numerical baseline identity is:

`a036c410e0bb1ec670e3fa0f7d6e14e1433322b6eeabdaa81c25c8daee43a29c`

Its schedule source is pinned to `nfldata` commit:

`67fa4d790ba09e5f0e2868b49ef9dbbd8946bb22`

The target is `fantasy_points_ppr` for QB, RB, WR, and TE rows.

Weekly statistical features remain leakage-safe: lagged and rolling statistics are built from chronologically prior observations, and the benchmark trains each fold only on earlier season-week blocks.

## Walk-forward evaluation

The existing multi-season benchmark operator is retained rather than replaced for this experiment.

- training precedes each evaluation block;
- minimum training history is 24 weeks;
- the quantile model is retrained every four weeks;
- the primary probabilistic score is mean pinball loss across q10, q50, and q90;
- the primary effect is `reference_loss - candidate_loss`, so positive values favor official availability;
- paired uncertainty is block-bootstrapped by season-week rather than by individual player row.

This preserves within-week player correlation in the resampling unit.

## Registered gates

The confirmatory run uses 2,000 season-week bootstrap samples and the following unchanged gates:

| Gate | Registered requirement |
| --- | ---: |
| Source coverage | >= 0.80 |
| FDR q-value | <= 0.10 |
| Season consistency | >= 0.55 |
| Position consistency | >= 0.55 |
| Week consistency | >= 0.55 |
| Paired rows | >= 250 |
| Paired seasons | >= 2 |
| Paired season-week blocks | >= 8 |
| Overall 80% interval coverage-gap regression | <= 0.02 |
| Worst supported-position coverage-gap regression | <= 0.05 |

In addition, the incremental effect and its lower 95% bootstrap confidence bound must both be positive.

## Negative controls

A positive raw lift is not enough.

### Identity shuffle

Official-availability features are shuffled within season, week, and position strata. The real official-evidence candidate must beat this shuffled control with a positive confidence interval. This guards against the model benefiting merely from player identity, injury-report membership, or other non-causal structure associated with who tends to appear in reports.

Failure of this control blocks the model gate.

### Shifted-time leakage sensitivity

A separate diagnostic shifts next-observation evidence backward in time. It asks how much apparent advantage becomes available when future information is intentionally leaked into an earlier row. This is reported as a leakage-sensitivity diagnostic and must not be confused with legitimate candidate lift.

## Multiplicity

The evidence framework applies Benjamini-Hochberg correction across the registered intelligence families. The official-availability experiment therefore does not switch post hoc to a one-family significance test simply because only injury evidence is currently populated. Doing so after seeing results would reduce the multiplicity burden and make the criterion easier.

## Calibration protection

The experiment evaluates more than pinball loss. It records q50 MAE and q10-q90 empirical coverage for the reference and candidate, then checks:

- overall interval coverage-gap regression;
- worst regression among position slices with enough paired rows.

An accuracy gain that materially damages uncertainty calibration is not eligible for activation review.

## Authority boundary

Every artifact produced by this experiment is `research_evidence_only`.

A successful result means only that the official-availability family is eligible for **manual activation review** under this newly frozen v2 baseline. It does not:

- modify production projections;
- modify the activation registry;
- prove historical production parity;
- prove causal injury effects;
- authorize broader news/persona evidence;
- automatically justify using the feature in every fantasy league or target.

If the combined official-availability family passes all gates, the next scientific step should decompose practice participation and game designation under a registered follow-up rather than guessing which sub-signal generated the lift.

## Reproduction

The manual GitHub Actions workflow `Historical official availability v2 REG experiment` restores the registered source-byte artifact, captures the exact Python/package environment, revalidates the core corpus contracts, and runs the registered experiment.

The local operator is:

```bash
python scripts/run_reg_historical_intelligence_experiment_v2.py \
  --numerical-root data/raw/historical_numerical_baseline_v2 \
  --injury-root data/raw/historical_injury_archive_v2 \
  --seasons 2020 2021 2022 2023 2024 \
  --target fantasy_points_ppr \
  --config configs/base.yaml \
  --bootstrap-samples 2000 \
  --minimum-source-coverage 0.80 \
  --maximum-fdr-q 0.10 \
  --minimum-consistency 0.55 \
  --minimum-paired-rows 250 \
  --minimum-seasons 2 \
  --minimum-blocks 8 \
  --minimum-position-rows 50 \
  --maximum-overall-coverage-gap-regression 0.02 \
  --maximum-position-coverage-gap-regression 0.05 \
  --output-dir artifacts/intelligence_ablations/historical_official_v2_reg
```

The runner refuses to execute this registered analysis if the numerical baseline identity differs from the registered SHA.

## Result

The result is intentionally not pre-populated in this protocol document. It should be written only from the completed immutable Actions evidence bundle, including the primary effect, confidence interval, FDR q-value, consistency metrics, negative controls, calibration diagnostics, source coverage, blockers, and artifact identity.
