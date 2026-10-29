# BDB27: Side-aware movement research v1

**Status:** executable, synthetic-tested **research foundation**. Not an NFL scouting score, injury-risk model, gaze estimator, or production fantasy feature. No official 2027 CSV has been opened in this development environment; no real-player effect has been measured. The competition requires an explicit Combine-to-NFL performance link for a scored submission. This PR does not claim to have completed that analysis.

## Scope and boundaries

This independent package lives in `src/player_state_engine/research/` so that the existing forecasts, Play Lab, and stacked AngleIQ #114 stay unchanged.

- **Observed**: canonical per-athlete 10 Hz x/y trajectories; fixed-field coordinates with explicit units and handedness; explicit optional ball reference and offense direction.
- **Derived**: signed **velocity-path** turns, entry/exit speeds, turn-angle bins, right-vs-left relative speed retention in comparable motion-demand strata. A left path turn **does not imply** left leg loading, left head orientation, player-side assignment, or leftward looking.
- **Geometry-only proxy**: externally supplied 3D head/torso orientation can produce *heuristic* alignment scores against candidate objects with explicit `UNKNOWN` mass. Not measured gaze, vision, fixation, attentional understanding, or evidence of tactical awareness.
- **Not available in competition tracking alone**: plant-foot identity, neck rotation, gaze, physiological strain, contact force, medical risk, player intention, coverage assignments, or scenario-optimal decisions.

## Canonical tracking CSV input contract

One row per sample with exactly **explicitly constructed** keys:

| Column | Required meaning |
| --- | --- |
| `source_kind` | literal `combine` or `nfl` |
| `source_id` | a source-scoped drill or game identifier; do **not** mix separate drill conditions |
| `segment_id` | one **contiguous**, independent attempt or player-play; no cross-play stitching |
| `player_id` | stable, **source-verified** player ID; never join by name |
| `frame_id` | strictly consecutive integer within source/segment/player |
| `time_s` | **seconds**, strictly 0.1 s separated at 10 Hz |
| `x`, `y` | **yards** in fixed-field right-handed axes (+X east, +Y north) |
| `position` | optional (WR, TE, DB, OL, DL); must be constant within a segment |

**Critical:** Official raw coordinate direction, drill attempt key, units, timestamps and field transforms must be verified against the downloaded official 2027 data dictionary. Do not feed CSVs directly based on older BDB schemas or infer anatomical sides from raw `dir`. The v1 package intentionally does not silently guess source field mappings. There is no authentication of source license/provenance from these files. Competition data stays outside Git.

When using a game scene, `field_context(x, y, offense_direction=+1/-1, ball_y=...)` returns **distinct** offensive left/right, boundary/field side, and distance to sideline. It abstains on boundary/field near a centered ball or without `ball_y`. The frame coordinate convention must be established for the source before using these labels. The ball hash, offensive direction, and actual assignment must not be conflated with anatomical handedness.

## Running the self-contained offline pilot

```bash
python -m pip install -e '.[dev]'
pytest -q tests/research
python scripts/run_bdb27_bilateral_pilot.py \
  --input-csv /local/canonical_tracking.csv \
  --output-dir /local/bdb27_pilot
```

Use `--synthetic-fixture` **only** for generated demonstration data. The script streams input SHA-256, doesn't modify/copy raw input, and emits `events.csv`, `asymmetry_profiles.csv`, and `manifest.json` with `RESEARCH_ONLY_NO_PROMOTION`. Put real and derived restricted data in an ignored, access-controlled local directory.

## Scientific design

1. First qualify each sample segment (identities, monotonic frames, finite coordinates, contiguous 10 Hz cadence); fail closed on gaps. In production research, split gapped segments upstream with provenance and characterize lost coverage.
2. Each candidate turn compares averaged incoming and outgoing displacement over two-frame windows. Turn sign is determined by the signed cross product in a **documented right-handed frame**. Thresholds are predeclared; overlapping candidate detections receive nonmaximum suppression.
3. A signed asymmetry summary uses `(right retention - left retention) / average(right, left) * 100`, **only** in overlapping entry-speed (2 yd/s) and turn-angle strata. At least three distinct attempts per direction are required.
4. Uncertainty uses a deterministic block bootstrap of **whole attempts**, preserving both turn directions when they occur in one segment. Insufficient independent trials, nonoverlap, or failed bootstrap coverage produces `insufficient_matched_evidence`, never a fabricated neutral score.
5. Above all, the signed value is a measurement hypothesis, **not** an injury diagnosis, a neurological inference, or a proof that one direction is better. Matching speed and turn bins does not control for assignment, effort, angle approach, task choice, or location.

Current extractor is a baseline, not a validated biomechanical event classifier. Sensitivity to smoothing, noise, drill-specific movement sequences, and frame transforms must be tested against human-reviewed reference examples before field claims.

## Position-specific decision-profile contracts

`position_profiles.py` exposes what each position's question would **require**, and whether supplied sources support it. It returns evidence eligibility and missing sources, never an unjustified skill score. Start with DB turns and OL lateral recovery, but preserve role/context differences within each position group.

| Group | Tracking-only exploratory quantity | More demanding decision question |
| --- | --- | --- |
| DB | directional reversal | coverage assignment and pre-break visual sampling |
| WR | turn reacceleration | route arrival relative to coached timing |
| TE | transition recovery | selection of correct blocking threat |
| OL | lateral reversal | identification of switching pass-rush threat |
| DL | curved rush retention | changing plan when blocked |

## Gaze and head/neck research interface

`head_attention.py` accepts **external**, rights-qualified head and torso pose estimates. It does **not** decode NFL film or estimate eye movement. It keeps separate `head_relative_torso_deg` and normalized `HEAD_ALIGNMENT_PROXY` target likelihoods. An optional verified eye/head offset marks `CALIBRATED_GAZE_CANDIDATE_INFERENCE`, still **not** measured fixation or awareness. Invalid/missing head pose returns `UNKNOWN=1` and `abstain`. Every score retains source ID; per-target outputs are *heuristic*, not calibrated posterior probabilities.

A future, independently reviewed AngleIQ adapter may use rights-authorized, hash-verified, synchronized multi-view local media; it must preserve its existing conservative rights declaration, no official-video downloading, and manual synchronization/visibility provenance. Never inject vision outputs into the public fantasy product, draft ranks, or automatic player evaluations without external validation and an explicit promotion decision.

## Required next gates before making a competition claim

- Obtain official 2027 data via authorized means and inspect the **actual** dictionary, attempts, coordinate frame, and player joins. Freeze source hashes, version, group sizes, source rights, eligible cohorts, and missingness.
- Make a source-specific adapter with tests for unit conversion, y-axis handedness, 0/120 yard geometry, drill aliases, combine attempt separators, NFL play changes, and player joins. No implicit mappings.
- Human-annotate a stratified sample of Combine turn segments, including ambiguous and low-speed examples; report precision/recall and inter-rater agreement.
- Analyze left/right measurement reliability and sensitivity to cadence, smoothing, bin edges, and event detection thresholds; estimate measurement errors.
- Match **player roles, start direction, entry speed, turning magnitude, field side, and task type**. A positive predictive result must survive nonmatching/shuffled controls and true held-out player/class validation.
- Predefine a game-performance target and correct observation window; compare size/standard Combine baselines, ordinary tracking, then asymmetry. Evaluate eligible-player coverage, confidence intervals, effect size, and negative controls. Don't claim awareness or injury risk from sensor coordinates.
- A real CV/eye-head experiment needs **licensed multi-view video**, camera calibration, synchronized eye-tracker ground truth, body/helmet/neck validation, and held-out people and cameras. Compare head-only, head+torso, context-only, and personalized fusion models on angular/target error and calibration. Never treat plausible helmet pointing as measured gaze.

## Integration and ethics

Do not commit source NFL media, competition CSVs, derived player-level restrictions, private face imagery or sensitive biometric features. Retain source licenses, consent and retention limits. Per-player metrics should include sample size, uncertainty, observed conditions and an explicit insufficient-evidence state. This PR is intentionally isolated from the existing product and stacked AngleIQ branches.
