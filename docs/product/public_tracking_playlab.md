# Public Tracking Play Lab: Original NFL Big Data Bowl Example

## Why this is worth integrating

The NFL Football Operations team maintains a historical open GitHub repository
with a **real 2017 game** of Next Gen Stats tracking, plus a complete player,
game, play and event schema. It is an unusually low-friction development
fixture for an actual football playback viewer, without Kaggle account setup or
private APIs. It is NOT the 2026 season and does not provide live positional
tracking. Respect the source's original contest rules before reusing it in
a public or commercial product.

Source repository:
https://github.com/nfl-football-ops/Big-Data-Bowl

NFL animation tutorial and schema:
https://github.com/nfl-football-ops/Big-Data-Bowl/blob/master/README.md
https://github.com/nfl-football-ops/Big-Data-Bowl/blob/master/schema.md

### A fully identified example to inspect

The original NFL tutorial uses game **2017090700**, play **938** (an Alex Smith
7-yard TD pass to Demetrius Harris). Our separate longer example is play **2756**
from Kansas City at New England on September 7, 2017.

Its public plays CSV identifies a **75-yard Alex Smith to Tyreek Hill
touchdown**, third quarter, 9:28 remaining. The offense was KC, the away
team, lining up in shotgun, with 1 RB / 1 TE / 3 WR. The separate official
games CSV establishes KC as visitor and NE as home.

Source records, which establish the above facts:
https://raw.githubusercontent.com/nfl-football-ops/Big-Data-Bowl/master/Data/plays.csv
https://raw.githubusercontent.com/nfl-football-ops/Big-Data-Bowl/master/Data/games.csv

These describe the published historical play outcome. The spatial route
coordinates must be read and validated from the associated original tracking
CSV, and we do not redistribute that file in our source tree.

### Reproduce locally

1. Review source-specific usage rights and open the public tracking CSV:

https://github.com/nfl-football-ops/Big-Data-Bowl/blob/master/Data/tracking_gameId_2017090700.csv

2. Download the **raw** CSV to a local working directory.

3. Convert just the identified play using the existing command-line importer:

    python scripts/import_bdb_tracking.py \
      --format bdb2019 \
      --csv /path/to/tracking_gameId_2017090700.csv \
      --game-id 2017090700 --play-id 2756 \
      --offense-side away \
      --license-id "source-terms-reviewed" \
      --acknowledge-source-terms \
      --output /tmp/kc-ne-2017-play-2756.json

The offense-side field is optional, but do not supply it without checking the
home/away and possession mapping against independent source records. Omitting
it avoids pretending to know defensive coverage assignments. The converter
preserves original NFL player identities, recorded x/y and speed, timestamps
derived from 10 Hz frame IDs, event markers and missing-frame counts. It does
not construct additional frames or ball height.

4. Run Fourth Down Lab locally. In GameDay Lab, select **Load historical replay
JSON** and choose your generated file.

5. In the field viewer, select an offensive or defensive player. Enable
**Nearest opponent** to see Euclidean field-space distance to the nearest
tracked opposing player in the current recorded frame. It is not necessarily
the defender responsible for coverage or a measure of individual skill.
Trails and camera angles remain optional.

No login, API token, tracking scraping or media copying is implemented.

## Validation and limitations

- Original data use frame.id rather than frameId and home/away instead of
  current-season team abbreviations. A separate adapter maps these fields to
  the stable HISTORICAL_RESEARCH JSON contract.
- Offense/defense sides require source-verified possession.
- Defenders may be nearest spatially without being assigned to the player.
- Frame gaps, absent ball positions, unknown ball height, team labels and
  undisclosed coach play calls remain explicitly missing or uncertain.
- A linear 2.5D projection is not the final 3D field mesh.
- For practical matchday use, continue separately developing a documented
  authorized live play-by-play feed and five-minute nflverse source cache.

## Additional zero-cost ideas

- **FTN formation tutor**: learn 11/12/21 personnel, defensive box counts,
  and pre-snap motion from postgame data. Availability is delayed, not live.
- **Route clustering**: compare observed real route shape and separation with
  league/personal historical priors, with explicit model error bars.
- **Field-state explainability**: display down/distance, expected points and
  hypothetical fourth-down options only when provenance supports those inputs.
- **Stadium wind overlay**: Open-Meteo is free for noncommercial use with
  attribution; attach only to outdoor or confirmed roof-open stadiums.
- **Source inspector**: each visualization layer should show whether it is
  observed tracking, charted annotation, estimated quantity, or illustration.

Data sources:
https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html
https://nflreadr.nflverse.com/reference/load_ftn_charting.html
https://open-meteo.com/en/terms

## Smoke checks

    pytest -q tests/product/test_gameday_tracking.py \
      tests/product/test_gameday_legacy_tracking.py

    cd apps/gemini-fantasy-console && npm run build

The currently merged Chromium smoke uses an explicitly generated fixture, not
actual NFL tracking. To qualify downloaded official bytes and a source-verified
home/away possession join, follow
[the real-source qualification guide](bdb2019_real_source_qualification.md).
A full first-party NFL data qualification workflow exists but runs only after
explicit source terms review. Actual original video alignment remains a separate
gate. Passing fixture tests alone cannot certify the real tracking.
