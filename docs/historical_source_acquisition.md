# Historical source acquisition and ablation

## Sources

The acquisition script declares immutable nflverse release assets for:

- weekly offensive snap counts;
- play-level participation and play-by-play;
- official injury reports;
- weekly depth charts and rosters;
- combine results and draft picks.

Run:

```bash
python scripts/acquire_historical_sources.py --seasons 2020 2021 2022 2023 2024 2025
```

Every downloaded file is stored unchanged and recorded in CSV/JSON manifests with URL, byte size and SHA-256.

## Point-in-time rules

- Snap counts are previous-game facts and are shifted one player-week.
- Pass-play participation is shifted one player-week. It is a route proxy, not proof that a route was run.
- Untimestamped depth charts are shifted one week.
- Same-week official injury evidence is included only when `date_modified` precedes a schedule-derived prediction cutoff.
- Missing source seasons remain missing. They are not encoded as healthy, inactive or zero usage.
- PFR snap IDs are crosswalked to GSIS IDs using weekly rosters, with the match method retained.

## Run the actual-source experiment

```bash
python scripts/run_historical_source_ablation.py \
  --data-dir data/raw/historical_sources \
  --schedules data/raw/nflverse/schedules.parquet
```

The outputs include source coverage, feature manifests, season metrics, position metrics, predictions, shuffled-player controls and a future-shift leakage control.

## Current packaged result

The isolated build environment could not transfer GitHub release binaries, so the repository does not claim an official-injury or snap-count performance gain. It does include a completed frozen proxy experiment over 23,003 out-of-sample player-weeks. Repackaged lagged box-score opportunity features worsened mean pinball loss by 3.14%, while the deliberately leaked future-shift control improved it by 27.04%. This establishes that the evaluation is sensitive, but that genuinely new source information is required.
