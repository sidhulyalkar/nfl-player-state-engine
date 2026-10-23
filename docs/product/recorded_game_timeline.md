# Recorded Game Timeline v1 (source-verified historical metadata)

**Status:** stacked development branch on historical play catalog PR #101. Research-only. No live tracking, fabricated drives, fantasy grading or source redistribution.

## Why

The 177-play metadata-only tracking atlas is a valuable start, but it knows
only frame/event coverage, not game situations. The independent, pinned official
NFL Big Data Bowl 2019 `plays.csv` and `games.csv` carry possession,
quarter, down, yards-to-go, and some charted play annotations. This feature
joins those verified files to the locally generated metadata-only catalog,
without exporting tracking coordinates.

The exported file contains ONLY game/play IDs, source file SHA-256 identities,
charted metadata, source tracking row counts, and explicit false authority
flags. It carries no raw records, player trajectories, inferred drive numbers,
coaching decisions or invented game clocks.

## Reproduce locally (after reviewing the source terms)

Obtain the original three official Big Data Bowl files, pinned and identified in
`docs/product/bdb2019_real_source_qualification.md`, in a **private**
directory and prepare the source-only tracking catalog as described in
`docs/product/public_tracking_playlab.md`.

    python scripts/build_bdb2019_play_catalog.py \
      --csv data/external/bdb2019-private/tracking_gameId_2017090700.csv \
      --license-id "ACTUAL_SOURCE_TERMS_IDENTIFIER_YOU_REVIEWED" \
      --acknowledge-source-terms \
      --output /tmp/pse-recorded-play-catalog.json

    python scripts/build_bdb2019_game_timeline.py \
      --source-dir data/external/bdb2019-private \
      --catalog /tmp/pse-recorded-play-catalog.json \
      --license-id "ACTUAL_SOURCE_TERMS_IDENTIFIER_YOU_REVIEWED" \
      --acknowledge-source-terms \
      --output /tmp/pse-recorded-game-timeline.json

Load Fourth Down Lab > GameDay Lab:

1. **Load play catalog JSON** with the catalog generated from the same tracking file.
2. **Load verified game timeline JSON** with the sidecar generated above.
3. Browse source-labeled plays by quarter, text, team or loaded replay availability.
4. Optionally import separately normalized historical tracking replay JSONs and
   open a verified matching replay. Missing replays stay in the timeline with
   no synthetic replacements.
5. **Back to play atlas** returns to the original frame/event overview.

The exporter verifies all three **whole source file Git blob hashes and lengths**
before performing the join. For an official source, it also independently rescans
all 316,025 tracking rows and requires the entire 177-play catalog (including
per-play observation counts and frame/event evidence) to match exactly; merely
claiming the correct tracking-file SHA in a manually edited JSON is insufficient. It requires all tracked play IDs in the catalog to
have exactly one matching official `plays.csv` row and reconciles possession
against home/away identities from `games.csv`. The browser independently
checks game ID, tracking source SHA, play count, play IDs and tracked row counts,
but cannot authenticate a user's local CSVs from a self-declared JSON alone.

**Drive caveat:** play IDs provide a source sort order, not a verified drive ID.
No consecutive-possession heuristic or inferred drive grouping is used. Real
drive navigation requires an independently validated play-by-play drive ID source.

## Validation

    pytest -q tests/product/test_bdb2019_game_timeline.py \
      tests/product/test_bdb2019_play_catalog.py

    cd apps/gemini-fantasy-console
    npm ci
    npm run build
    npm run test:field3d

Negative controls reject modified source blobs, mismatched tracking SHA,
missing/duplicate play joins, invalid possession identities, false drive
authority, fabricated current-game status and mismatched loaded replay frames.
Only the synthetic fixture is exercised in CI. The complete official-source
177-play timeline and browser import still need local qualification on the
actual user-supplied source files, and original-video alignment remains pending.

This implementation does not change any NFL projection, model serving,
scoring, lineup, or fantasy champion-selection authority.
