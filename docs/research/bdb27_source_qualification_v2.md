# BDB27 source qualification v2: Combine and rookie NFL movement

Status: **research-only, not a validated NFL result**. Proposed implementation is stacked on PR #115 and does not affect fantasy predictions or AngleIQ. Official licensed 2027 CSV bytes were not available in the development environment; all tests are synthetic. Source semantics follow a 2027 participant's publicly described data fields and MUST be verified against the primary Kaggle data dictionary before interpretation.

## Scientific hypothesis

Does a repeatable directional movement signature measured in a specified Combine drill reappear in a player's **rookie regular-season NFL** movement, and does it subsequently add decision value beyond conventional testing? This v2 package assesses observability and eligibility, **not** the final prediction or causal hypothesis.

Do not infer plant-foot identity, left/right limb forces, head/eye gaze, visual attention, cognitive awareness, or injury risk from tracking positions. The field's `boundary`/`field` side cannot be estimated from player Y alone. Source orientation declarations do not authenticate NFL data semantics.

## Required private inputs

Get the official 2027 competition download after accepting its applicable rules on Kaggle. Keep it in an access-controlled local directory outside Git. The first qualification stage requires `players.csv`, `combine_tracking.csv` with columns `nfl_id, entity_type, drill_type, drill_name, attempt, event_id, time, x, y`. The second requires `players.csv`, `games.csv` with `game_id, season, season_type`, and `game_tracking_{season}.csv` with `game_id, play_id, nfl_id, x, y, frame_id` or `time`. These are *adapter expectations*, not claims of having audited the official data dictionary.

The official competition dataset has been described as nine CSV files for 2023–2025 prospects across DB, WR, TE, OL and DL. Before any scoring, verify file headers, units, time semantics, coordinate axes, data rights, and whether each drill/event ID denotes a true independent attempt. A player may have many tracking frames but only one useful trial. The 2027 data are noncommercial; don't commit raw tracking or player-level derivatives.

## Run locally

```bash
python -m pip install -e '.[dev]'
PYTHONPATH=src:. pytest -q tests/research

# Explicitly verify axis handedness using the official source dictionary first.
python scripts/qualify_bdb27_combine.py \
  --source-dir /secure/bdb27 \
  --output-dir /secure/research/combine \
  --y-axis-sign 1 \
  --acknowledge-competition-data-terms

python scripts/qualify_bdb27_rookie.py \
  --source-dir /secure/bdb27 \
  --output-dir /secure/research/nfl-2023-DB \
  --position DB --rookie-season 2023 --y-axis-sign 1 \
  --acknowledge-competition-data-terms

# Repeat game audit for 2024 and 2025, each with a distinct output directory.
python scripts/build_bdb27_transfer_audit.py \
  --combine-dir /secure/research/combine \
  --nfl-dir /secure/research/nfl-2023-DB \
  --nfl-dir /secure/research/nfl-2024-DB \
  --nfl-dir /secure/research/nfl-2025-DB \
  --output-dir /secure/research/transfer --position DB
```

Use the actual physical `Y` convention determined from the source; the `--y-axis-sign` argument is a user declaration, not a means of auto-verifying the coordinate system. The NFL adapter reflects around the real field width under `-1`; the Combine adapter reflects around local Y=0. These frames are not inherently aligned for side interpretation and cross-domain sign comparisons are **not validated** until carefully documented and checked.

Outputs include trial/play coverage tables, detected turn events, eligibility by position/drill and separated-replicate uncertainty intervals, source SHA-256 digests and a descriptive transfer coverage table. **Do not put any of these private player-level output files in a public PR**. The transfer runner rejects a mismatched player registry hash and repeated season artifacts; it deliberately provides no performance correlation or scouting ranking.

## Data and model gates

1. **G0 Source:** User confirms authorized access; exact source file hashes, headers, units and complete season files qualified. Unknown or duplicate event IDs/times, nonfinite coordinate values, unjoined Combine players, invalid game IDs and samples outside the declared years fail explicitly.
2. **G1 Tracking:** Detect gaps and teleports without interpolation. Preserve source `independent_trial_id` across every contiguous subsegment; exclude too-short fragments. Report all excluded coverage in the manifest.
3. **G2 Asymmetry:** Separate right-handed path-turn direction from offensive left/right and from anatomical loading. Require independently repeated trials in **both** directions, matched entry-speed and turn-angle bins, and enough bootstrap coverage. If data are sparse, return `insufficient_matched_evidence`.
4. **G3 Rookie linkage:** Only `season_type=REG` in a player's draft season. Count eligible players, frames and unique player-plays; never use veteran seasons as rookie outcomes. Keep unlabeled ball/field side unknown.
5. **G4 Measurement validation:** Manually annotate a stratified sample of drill trajectories; predefine turn tolerance and compare detector precision/recall. Analyze detector sensitivity to windows, thresholds, clipping, dropout and coordinate reflections. No automatic promotion based on synthetic success.
6. **G5 Prediction, future:** Freeze one DB or DL drill and an independently justified NFL endpoint. Compare conventional Combine baseline, simple sensor metrics and signed/sequence metrics on exactly the same player-disjoint, draft-cohort holdout. Report player-level confidence intervals, sample denominators and negative controls; do not select features on the final holdout.

## Manual event-detector validation

Before trusting any player asymmetry, independently review a prespecified, representative sample of complete raw drill attempts, including **no-turn trials**. Reviews should be blind to the model output. Save:

- `reviewed_trials.csv`: one row per complete trial and annotator with `source_kind,source_id,player_id,independent_trial_id,annotator,complete_review` (boolean true).
- `human_labels.csv`: one row per human-labeled event with those five identity fields plus `time_s,turn` (`left`/`right`). No-turn trials have **no positive label rows** but remain in reviewed_trials.
- `turn_events_RESEARCH_ONLY.csv`: automatically generated detections with the same original-trial time base.

Run:

```bash
python scripts/evaluate_bdb27_turn_annotations.py \
  --detections /secure/research/combine/turn_events_RESEARCH_ONLY.csv \
  --reviewed-trials /secure/research/reviewed_trials.csv \
  --human-labels /secure/research/human_labels.csv \
  --output-dir /secure/research/event-validation --tolerance-s 0.2
```

The evaluator uses one-to-one temporal matching within each original trial and direction, reports precision/recall/F1 **separately by annotator**, and does not confuse absent labels from unreviewed trials with true negatives. Review selection should include drills, positions, seasons, low/high speed, occlusion/low-quality examples, and random no-turn trials. Assess rater agreement and tune any detector only on development reviews, preserving a frozen held-out human-reviewed sample.

### Candidate negative controls

- Shuffle player identities within position and draft class before linkage.
- Reverse the source Y coordinate sign: signed turns should reverse while absolute curvature is preserved.
- Duplicate only tracking fragments: independent attempt count must not increase.
- Break tracking time or insert implausible jumps: fragments should be discarded or split, not interpreted as explosiveness.
- Use a mismatched player source hash: cross-source linkage must fail.
- Remove or scramble field context: boundary/field scoring must abstain.

### Known limitations

The dataset was **not** provided in this runtime; real-player qualifying counts and empirical NFL results remain unknown. The public first-look studies on 2027 data suggest that position drills may have weak retest reliability, making abstention likely and scientifically important. Derivative estimates from 10 Hz tracking are sensitive to filtering, and physical plant-side identity cannot be recovered solely from trajectory curvature. No prospective outcome improvement, no gaze reconstruction, no injury load estimates, and no field-side strain inference have been established.

### Next required evidence

Run these adapters on authorized source files and inspect `eligibility_by_drill.csv`. Choose one drill with sufficient *independent players* and comparable right/left trials, then label a sample of raw movement events. For an NFL performance metric, join only a prespecified rookie-season, position-appropriate endpoint with a documented denominator. If a drill has inadequate replication or no transfer overlap, reject it and compare an alternative drill rather than relaxing gates after observing results.
