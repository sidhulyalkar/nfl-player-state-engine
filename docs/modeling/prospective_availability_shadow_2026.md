# Prospective 2026 official-availability shadow

## Purpose

This lane exists to create a genuinely prospective observation dataset for official injury and practice evidence during the 2026 regular season.

The historical v3 experiment was post-hoc by construction: its current-week formulation was designed after observing the failed v2 result. The completed v3 artifact subsequently rejected **all three** registered formulations (`practice_current_week`, `game_designation_current_week`, and `combined_current_week`). None passed the exploratory predictive screen, and none is eligible for prospective confirmation or activation review.

The 2026 shadow lane remains useful for a different reason: it freezes the evidence that was actually available to this project before each game's prediction cutoff. Those immutable observations can support future **materially new, preregistered** availability or participation hypotheses without reconstructing publication history after outcomes are known.

Everything produced here has authority `prospective_shadow_evidence_only`. It cannot alter production projections, player rankings, draft values, or the activation registry.

## Core point-in-time rule

**Collection time is authoritative.**

For every source snapshot, the system records `source_collected_at_utc` from the machine clock at download time. Publisher metadata such as `date_modified` is retained for audit, but it cannot backdate evidence availability.

A row is eligible for a future prospective evaluation only when:

```text
source_collected_at_utc <= kickoff_utc - 1.5 hours
```

A source row downloaded after the prediction cutoff remains in the immutable audit bundle but has `usable_before_cutoff = false` for that game.

This deliberately prefers false negatives over hindsight leakage.

## Why this differs from historical reconstruction

Historical archives answer: "What does the final archive say happened?"

The prospective shadow answers: "What bytes had this project actually observed by the decision time?"

That distinction matters when mutable feeds are corrected, republished, delayed, or unavailable. The 2026 observation dataset must never infer an earlier availability time from a later download.

## Snapshot contents

Each successful capture stores:

- the exact mutable injury source bytes as `injuries_source.csv`;
- the exact commit-pinned schedule bytes as `schedule_source.csv`;
- a normalized `availability_snapshot.csv` containing only current-week availability fields and game cutoffs;
- `manifest.json` with collection time, source URLs, byte counts, SHA-256 identities, schedule commit, team-observation diagnostics, row counts, and authority metadata.

The bundle is therefore self-contained even if an upstream source later changes or disappears. The normalized snapshot intentionally excludes player game outcomes, and the manifest asserts `contains_player_outcomes = false`.

Snapshot directories are content/time addressed:

```text
artifacts/prospective_availability_shadow/
  season_2026/
    week_01/
      20260913T150000Z_<injury-sha-prefix>/
```

Existing snapshot directories cannot be overwritten.

## Source-unavailable behavior

A missing injury release is evidence about source availability, not evidence about players.

If the configured injury URL returns HTTP 404, the collector writes a `source_unavailable_*.json` record with zero evidence rows and exits cleanly. It never interprets source failure as "healthy", "not listed", or zero injury risk.

This is important because nflverse injury releases have had availability gaps in prior seasons.

## Conservative team-source audit

A globally downloadable file does **not** prove every scheduled team's report is complete.

For every scheduled team, `manifest.json` records a `team_observation` entry containing:

- game and team identity;
- the game's 1.5-hour cutoff;
- actual collection time;
- whether collection occurred before that cutoff;
- `team_row_observed`, meaning at least one current-week source row for that team existed in the downloaded bytes.

The manifest also records `scheduled_teams`, `teams_with_source_rows`, and `conservative_team_row_observation_rate`.

A scheduled team with zero source rows is deliberately **not** interpreted as a clean injury report. It may mean no listed injuries, a delayed team report, or incomplete upstream coverage. Later evaluation must keep that state unresolved unless report completeness is established independently.

This mirrors the fail-closed philosophy of the historical corpus: absence of evidence is never promoted into evidence of health merely because a file downloaded successfully.

## Schedule authority

Each capture resolves the latest Git commit touching `nfldata/data/games.csv` at capture time and then downloads `games.csv` from that exact commit SHA. The snapshot manifest records:

- schedule commit;
- commit-pinned schedule URL;
- schedule byte count;
- schedule SHA-256.

The exact schedule bytes are also retained in the snapshot directory.

## Current-week semantics

The collector canonicalizes only the requested 2026 regular-season week. When multiple source rows exist for the same player/team/week, the latest row in the bytes observed at collection time is retained.

For each player evidence row it stores:

- team and game identity;
- practice status;
- game/report status;
- primary injury;
- publisher `date_modified` as audit metadata;
- actual collection timestamp;
- 1.5-hour prediction cutoff;
- `usable_before_cutoff`.

A future preregistered model may derive treatment features from these immutable snapshots. The collector itself does not score or model players.

## Capture cadence

The initial workflow is deliberately **manual-only**. Before the regular season begins, this avoids generating meaningless off-season artifacts or silently creating a cadence we have not audited.

During the season, the safest collection policy is multiple immutable captures during each reporting week, including one sufficiently close to the 1.5-hour cutoff. A later preregistered evaluation should select the latest capture that was actually collected before each game's cutoff.

A scheduled capture workflow can be added only after the manual path is qualified and the 2026 source URL is observed to be stable enough for unattended collection.

## Workflow concurrency

PR qualification and scientific capture use different concurrency semantics:

- obsolete PR-head qualification runs are canceled when a newer commit arrives;
- each manual capture uses its unique workflow run ID and can never be canceled by a later manual capture.

This keeps CI economical without discarding a real point-in-time scientific observation.

## Artifact-retention limitation

GitHub Actions artifacts are useful operational transport but are not permanent scientific storage. The initial workflow uses them to qualify the collector and capture snapshots, but 90-day artifact retention is not a sufficient season-long archival strategy.

Before relying on this lane for end-of-season prospective evaluation, the project should add durable immutable storage with the same SHA-addressed snapshot contract. Until then, the raw snapshot directory produced by each run is the scientific payload, while the Actions artifact is only its temporary carrier.

## Manual workflow

Run `Prospective 2026 availability shadow capture` and provide the regular-season week. The workflow:

1. checks out the exact code head;
2. installs and tests the prospective collector;
3. resolves the current commit touching `nfldata/data/games.csv`;
4. downloads the commit-pinned schedule and current `injuries_2026.csv` source;
5. records the real collection time;
6. writes either an immutable snapshot or an explicit source-unavailable record;
7. captures the code SHA and Python/package environment;
8. uploads the complete shadow bundle as a non-production artifact.

The direct local operator is:

```bash
python scripts/capture_prospective_availability_snapshot.py \
  --season 2026 \
  --week 1 \
  --injury-url https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_2026.csv \
  --schedule-url https://raw.githubusercontent.com/nflverse/nfldata/<COMMIT>/data/games.csv \
  --schedule-commit <COMMIT>
```

Do not manually substitute an old collection timestamp. The CLI intentionally derives collection time from `datetime.now(UTC)`.

## Evaluation boundary after the negative v3 result

There is **no surviving v3 formulation to confirm prospectively**. The 2026 shadow data must therefore not be used to keep re-searching the same practice/game feature combinations until one appears favorable.

Any later predictive evaluation must be preregistered before outcome settlement and must state a materially different hypothesis, for example:

- explicit probability-of-active / participation modeling rather than a generic residual feature;
- hard game-status gating with a separately calibrated missingness policy;
- a participation head whose output feeds opportunity models rather than direct fantasy-point residual adjustment.

The hypothesis, feature semantics, cutoffs, baselines, negative controls, multiplicity policy, and promotion threshold must be frozen before scoring 2026 outcomes.

A successful future prospective experiment may become eligible for **manual activation review** under its own registered contract. It still must not auto-promote.
