# Private Play Lab research-session qualification

**Status:** opt-in local verification tool, research only. Synthetic CI does not
qualify the real 2017 NFL data. No live data, commercial use, training authority,
coverage assignments or game-film alignment is implied.

## Prerequisites

1. Independently obtain the exact pinned 2017 game tracking, games and plays
   CSVs in `data/external/bdb2019-private/` or another **private** location.
2. Read the actual applicable source-use terms and keep identifiers/restrictions
   with your local research notes. These instructions do not grant rights.
3. Build the position-free catalog and game timeline using
   `scripts/build_bdb2019_play_catalog.py` and
   `scripts/build_bdb2019_game_timeline.py`, with explicit terms acknowledgement.
4. Create a **new** private session directory with
   `scripts/export_bdb2019_replay_batch.py` and 12 distinct play IDs.

The pilot selector creates a **deterministic technical-coverage sample** from
the pinned source catalog: tutorial plays 938 and 2756 plus diverse recorded
frame spans, source gaps, excluded positions, ball availability and source
events. This is not a randomized sample or a claim about league-wide coverage.
The selection is position-free, SHA-256-bound to the audited original tracking
CSV, and cannot be reused with different source data or different license terms.

Unlike Bash `mapfile`, the commands below work directly on macOS.

```bash
python scripts/build_bdb2019_play_catalog.py \
  --csv data/external/bdb2019-private/tracking_gameId_2017090700.csv \
  --output /tmp/pse-recorded-play-catalog.json \
  --license-id "YOUR_ACTUAL_REVIEWED_TERMS_IDENTIFIER" \
  --acknowledge-source-terms

python scripts/select_bdb2019_pilot.py \
  --catalog /tmp/pse-recorded-play-catalog.json \
  --output /tmp/pse-private-pilot-selection.json \
  --license-id "YOUR_ACTUAL_REVIEWED_TERMS_IDENTIFIER" \
  --acknowledge-source-terms

python scripts/export_bdb2019_replay_batch.py \
  --source-dir data/external/bdb2019-private \
  --output-dir /tmp/pse-private-2017-session-v1 \
  --selection-file /tmp/pse-private-pilot-selection.json \
  --license-id "YOUR_ACTUAL_REVIEWED_TERMS_IDENTIFIER" \
  --acknowledge-source-terms
```

The exporter re-verifies the pinned official source files and rejects a
selection made from a different tracking SHA-256. It never grants new rights.
A preexisting selection/output path is not overwritten.


Make sure the catalog file was generated from the same pinned source. The
export fails atomically if any requested play is absent. Avoid committing the
JSON, local source CSVs or private browser traces.

## Real Chromium session check

Build the frontend and serve it locally in one terminal:

```bash
cd apps/gemini-fantasy-console
npm ci
npm run build
npm run preview -- --host 127.0.0.1 --port 4173
```

In another terminal, from the same frontend directory:

```bash
PLAYLAB_REAL_SESSION_DIR=/tmp/pse-private-2017-session-v1 \
PLAYLAB_EXPECTED_PLAYS=12 \
PLAYLAB_SOURCE_TERMS_ACKNOWLEDGED=yes \
PLAYLAB_SOURCE_LICENSE_ID="YOUR_ACTUAL_REVIEWED_TERMS_IDENTIFIER" \
PLAYLAB_LOCAL_REPORT_PATH=/tmp/pse-private-session-report.json \
node scripts/smoke_gameday_browser.mjs
```

This extends the ordinary synthetic Chromium smoke. The optional local
qualification step:

- Requires explicit source-terms acknowledgement and a license declaration
  matching the manifest.
- Checks manifest format, exact play count, safe file basenames, sizes and
  local replay SHA-256 hashes using streaming reads.
- Selects **all** manifest files in Chrome via local DevTools file-input APIs.
  Raw replay content is **not** serialized into the DevTools command or sent to
  the application server. The viewer independently runs its browser SHA-256
  and semantic consistency gates.
- Checks that the full playlist is present and hash verification was indicated.
  Measures wall time and available browser JavaScript heap after import.
- Writes only a small redacted research report if
  `PLAYLAB_LOCAL_REPORT_PATH` is supplied. The report file must not already
  exist, and is written with user-only permissions. No private-real-data
  screenshot or original tracking coordinates appear in it.

Run the qualification on a private workstation trusted to hold the data.
Chromium still reads the selected source replay files into its local browser
process. Ensure your preview server is **local only**; do not expose the
research app publicly while the private session is loaded.

## What is still NOT qualified

A successful report demonstrates local export-package consistency, ability
to load the entire browser session, and a sample performance observation.
It does **not** prove that the provided manifest is an official source identity
or authorize reuse. Original whole-source CSV bytes are qualified only by the
offline pinned-source exporter. Film event synchronization, scientifically
validated tactics, end-to-end frame timing and improved 2026 fantasy forecasts
remain separate open research gates.

For full release qualification, record environment versions, original-source
contract checks, reference source identity hashes, longest play, timeouts,
performance limits, 2D fallback, and replay evidence inspection in a private
review record. Do not merge on a single passing local smoke.
