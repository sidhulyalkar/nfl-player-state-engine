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

The hardened actual-source ablation is complete over 23,003 held-out player-weeks
from 2022–2025, with 2021 used for initial residual-model training. Coverage was
reported before metrics:

- snap evidence: 99.2–100.0%, with 97.8–98.8% player-ID resolution;
- pass-participation evidence: 92.6–95.1%, with 100% ID resolution;
- depth-chart evidence: 91.7–99.8%, with 99.0–100% ID resolution;
- official injury evidence: 16.6–18.2% in 2021–2024; the present 2025 file had
  no usable authored timestamps and therefore failed closed as unavailable/NaN.

No feature family passed promotion. The numerical baseline achieved 1.380323
mean pinball and 0.820936 q10–q90 coverage. The best eligible challenger,
`objective_sources_combined`, recorded 1.401138 mean pinball
(-1.508% versus baseline) and 0.717385 coverage. Every challenger lost in every
held-out season, although the combined source family showed a small isolated QB
gain that did not survive the full position/season gate. The shuffled-player
control lost 4.109%, while the deliberately future-shifted control improved
5.309%, confirming that the evaluation detects both destroyed identity and
future information.

The complete local experiment contract is written to
`artifacts/experiments/historical_sources_hardened_v05/`. Compact coverage and
summary tables are exposed to the Product API and Model Lab; large predictions
remain gitignored.
