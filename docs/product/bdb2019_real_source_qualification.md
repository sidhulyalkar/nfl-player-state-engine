# Qualify real NFL Big Data Bowl 2019 tracking

This is SOURCE AND STRUCTURE qualification, **not** original-video
alignment and not a determination of reuse, publishing or training rights.

## Official pinned source identity

Source: https://github.com/nfl-football-ops/Big-Data-Bowl
Revision: 9ad0b4b2ea36697e29e44e2399512cc1ce70358c

| Source in Data/ | Git blob SHA-1 | Size |
| --- | --- | ---: |
| tracking_gameId_2017090700.csv | 2394ce60e8947eb7e73d36515c021a0699768ca1 | 31,659,157 bytes |
| plays.csv | 08b1ad5f88efb89939c17a8793a55fcddf2511ca | 3,038,568 bytes |
| games.csv | 3835c453e8c37342394267c384948b7d88fe55f1 | 15,825 bytes |

These identities include the complete Git blob header and bytes. The
qualifier checks all three before interpreting the data and also computes
independent SHA-256 hashes for its report. A hash does not grant any license.

The NFL's own tutorial uses **game 2017090700 / play 938**, a seven-yard
Alex Smith to Demetrius Harris touchdown. Our second reference is
**game 2017090700 / play 2756**, a 75-yard Alex Smith to Tyreek Hill
touchdown. Both are from KC at NE on September 7, 2017.

Most importantly, the qualifier joins the *actual possessionTeam* column in
plays.csv with *homeTeamAbbr* and *visitorTeamAbbr* in games.csv. Offense and
defense are derived from this metadata, not the position of a receiver or
any guessed formation. The published offenseFormation and personnel.offense
fields are charted metadata, separate from recorded x/y.

## Reproduce privately after independently reviewing applicable terms

Install this repository into a virtual environment, then run:

    python scripts/qualify_bdb2019_example.py \
      --download \
      --source-dir data/external/bdb2019-private \
      --output-dir /tmp/pse-bdb2019-qualification \
      --game-id 2017090700 --play-id 938 \
      --license-id "ACTUAL_SOURCE_TERMS_IDENTIFIER_YOU_REVIEWED" \
      --acknowledge-source-terms

Use --play-id 2756 to examine the separate Tyreek Hill touchdown.

The downloader fetches only the three immutable official CSVs over HTTPS,
checks file sizes and pinned Git object hashes, and refuses to overwrite
existing files that differ. The output directory holds:

- A compact qualification JSON with joined metadata, SHA-256, source frame
  coverage, explicit snap labels, warnings and evidence status.
- A normalized research replay JSON containing recorded positions, for
  **private browser loading only**. Never add the output to source control.

Add --report-only to avoid writing the replay positions JSON.

The source status SOURCE_AND_STRUCTURE_QUALIFIED_VIDEO_PENDING requires
pinned official bytes, one unique matching game and play, verified
possession and structurally valid per-frame tracking. The report always
states source_video_alignment_verified = false. It does not conclude that
all observations are correct relative to game film.

## Manual-only GitHub Actions qualification

In GitHub Actions, run **Historical NFL BDB source qualification (manual)**.
You must personally check the terms acknowledgment and supply the source
terms identifier. The workflow runs only on an explicit manual trigger,
downloads sources into ephemeral runner storage and uploads ONLY its small
qualification report. No per-player positions or raw tracking are uploaded
as artifacts. Do not run it without source-use authorization.

## Playback and local smoke

Start the Fourth Down Lab frontend:

    cd apps/gemini-fantasy-console
    npm ci
    npm run build
    npm run preview -- --host 127.0.0.1 --port 4173

Open the GameDay Lab and load the private research replay via the local
file input. Inspect source-labeled frame IDs, snap event, nearest-opponent
measurement, measured travel direction, 3D camera and 2D fallback.

The optional headless Chromium smoke supports the local full research
replay via the environment variable PLAYLAB_REAL_REPLAY_PATH:

    PLAYLAB_REAL_REPLAY_PATH=/tmp/pse-bdb2019-qualification/2017090700-938-research-replay.json \
      node scripts/smoke_gameday_browser.mjs

The script uses google-chrome unless CHROME_BIN specifies another binary.
The real-data browser option validates the import/display workflow and
does not by itself qualify positional accuracy against video.

## Remaining scientific and product gates

- Compare event times, observed locations, field direction and individual
  routes with the NFL's original animation or lawfully accessed video.
- Verify the older direction-of-travel convention before implementing body
  facing. The original 2019 direction field measures *movement*, not gaze.
- Test screenshot legibility in Chromium, Firefox and Safari and measure
  memory and dropped animation frames with a long source play.
- Independently determine permitted data and screenshot uses under the
  actual source terms. Public accessibility is not a grant of rights.

No live NFL tracking, player-grade promotion, model training or commercial
license is established by this command.
