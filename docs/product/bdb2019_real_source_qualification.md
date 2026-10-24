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


## Real source-data audit: exact NFL tracking blob (2026-10-23)

We inspected the original 31,659,157-byte file from the NFL's published
2017 season sample, supplied privately by the user. It matches official
Git blob SHA-1 `2394ce60e8947eb7e73d36515c021a0699768ca1`
and source SHA-256
`30e0de5a213093011d16f7c0893fb6108284cb82be155b5e1bb14de754319f9b`.
The complete source contains 316,025 records across 177 plays, for game
2017090700. No copyrighted tracking records were committed.

Important discovery: the original NFL file calls the ball entity `team=ball`
(not just `football`). The BDB2019 adapter now accepts either label.

For the two publicly identified reference plays:

| Observation | Play 938 | Play 2756 |
| --- | ---: | ---: |
| Source rows | 1,426 | 2,691 |
| Recorded 10 Hz frames | 62 | 117 |
| Unique tracked players | 22 | 22 |
| Source-labeled snap frame | 15 | 15 |
| Source ball frames | 62 | 117 |
| Missing whole source frames | 0 | 0 |
| Position samples missing x/y | 0 | 6 |
| Source positions outside the 120 x 53.3-yard display bounds | 0 | 10 |
| Unrenderable observations excluded, NOT clipped | 0 | 16 |

On play 2756, the ten outside-field observations and six missing x/y
samples correspond to Malcolm Butler after he crosses beyond the sideline
late in the touchdown sequence (source frames 102-117). The source still
has 117 original frame IDs and its touchdown event in frame 107.
No positions are manufactured at the sideline.

The audited position policy retains such frames and event tags even when
a participant has no drawable on-field x/y. The replay JSON includes a
`position_quality` record, and the Play Lab displays its omitted-row
counts. Importer strict mode continues to reject missing/outside values.
The manual **real-source qualification** CLI uses the audited policy,
while the lower-level legacy importer defaults to strict. When calling the
generic importer directly for the longer play, specify:

    python scripts/import_bdb_tracking.py \
      --format bdb2019 --csv /path/to/tracking_gameId_2017090700.csv \
      --game-id 2017090700 --play-id 2756 \
      --offense-side away \
      --position-policy omit_off_field_with_audit \
      --license-id "ACTUAL_SOURCE_TERMS_IDENTIFIER_YOU_REVIEWED" \
      --acknowledge-source-terms \
      --output /tmp/pse-bdb2019-2756.json

The exact real-file frame, ball and omission counts are enforced by the
canonical qualification contract for both selected plays, so a changed
interpretation is visible in CI or manual source qualification.

**Scope of what was actually checked:** The exact tracking CSV was available
locally and its full-file blob hash was independently confirmed. Game/play
metadata for these two selected plays was checked against the NFL's official
Git source records via the GitHub integration. The entire original
`games.csv` and `plays.csv` were not downloaded into the local analysis
environment, and the manual all-three-source workflow has not yet run.
No original-video alignment, ball-height measurement or commercial reuse
approval is implied.


## Multi-play research session (local UI)

Fourth Down Lab now supports selecting several research replay JSON files at
once with the **Load historical replay JSON(s)** file picker. The uploaded
user-owned coordinates stay in React session memory. The panel exposes a
**Research playlist** to switch plays, while **Add replay JSON(s)** appends
another verified local file. The demo view retains a temporary play selector
until the page is refreshed or navigated away from.

For both original 2017 touchdowns:

1. Use the above qualification command to generate each play's JSON.
2. Select both JSON files from the local file picker (macOS: Command-click).
3. In the historical panel, switch between game 2017090700, play 938
   and game 2017090700, play 2756.
4. Compare snap-aligned observed positions, event frames, selected-player
   traveled distance, direction-of-travel arrows and exclusions. These are
   observations, not reconstructed coaching intent or film verification.

The research playlist is deliberately limited to 12 plays and 50 MB of
serialized replay data in one browser session, with a 25 MB per-file cap.
Conflicting normalized data for an existing game/play key are rejected,
not silently overwritten; identical duplicate imports are idempotent.
Importing a batch is atomic: one conflicting, corrupt or too-large file
must not partially alter the session.

No server upload, permanent storage or licensed live NFL feed is involved.
Refreshing the browser clears the session. Do not interpret the label
"Research playlist" as a dataset attestation or license approval.


## Whole-game play atlas from the verified 31 MB source

The optional metadata-only catalog generator scans the entire pinned NFL
tracking CSV in one pass, keeping source positions out of its JSON output:

    python scripts/build_bdb2019_play_catalog.py \
      --csv data/external/bdb2019-private/tracking_gameId_2017090700.csv \
      --output /tmp/pse-bdb2019-qualification/2017090700-play-catalog.json \
      --license-id "ACTUAL_SOURCE_TERMS_IDENTIFIER_YOU_REVIEWED" \
      --acknowledge-source-terms

The official pinned 2017 game currently contains **316,025 source rows
across 177 plays**. Of those, **60 plays** have at least one nonrenderable
on-field position, totaling **1,830** excluded source observations. These
are independent recorded position-quality measures; none are repaired,
clamped, used to train a model or represented as missing whole frames.

In GameDay Lab, select **Load play catalog JSON**. Search source event names
(e.g. touchdown, punt, ball_snap) or play IDs; filter by observation quality
and sort by play length. The browser reads **only metadata**, not the 31 MB
source file. When a matching historical replay JSON was already loaded into
the research session, a play has an **Open recorded replay** control.
Matching requires game ID, play ID, source SHA-256, frame count, source frame
gaps, and source-row counts when available. Otherwise the catalog shows
that the play's actual per-frame JSON must be imported before inspection.

The catalog's declared hash is checked structurally by the browser; it is
NOT cryptographically recomputed there against the 31 MB original source.
The local Python generator requires the original pinned Git object bytes
before declaring its source. Never publish raw tracking as a demo asset or
label catalog-only summaries as reconstructed NFL player coordinates.


## Batch qualification: open up to 12 source-verified plays in one pass

The single-play CLI above still works. For repeated comparison, the batch
exporter avoids rescanning and hashing the full 31 MB original file for each
selected play. It verifies all **three pinned source CSVs**, reconciles the
play IDs and official possession teams, partitions selected rows during a
single CSV scan, then reuses the existing audited replay adapter.

After independently reviewing applicable terms and placing the original
NFL files in your private `data/external/bdb2019-private/` directory:

    python scripts/export_bdb2019_replay_batch.py \
      --source-dir data/external/bdb2019-private \
      --output-dir /tmp/pse-nfl-2017-session-new \
      --play-id 938 \
      --play-id 2756 \
      --play-id 3725 \
      --play-id 4429 \
      --license-id "ACTUAL_SOURCE_TERMS_IDENTIFIER_YOU_REVIEWED" \
      --acknowledge-source-terms

The `--output-dir` path must **not already exist**. The exporter stages
everything in a sibling temporary directory and creates the final directory
only after all selected replays pass integrity and source-role checks.
A malformed, missing or conflicting play means **no session is produced**.
At most 12 distinct ASCII-numeric play IDs are accepted per batch; each is
limited to 25,000 original rows, with a 400,000-row source scan cap.

The output contains one `<game>-<play>-research-replay.json` per play and
a `manifest.json` with each output's SHA-256, frame/position counts,
source-file identities, and research-only disclaimers. No filtered raw CSVs
remain in the final directory. No positions are committed to the repo,
uploaded to a server, or incorporated into the production prediction model.

Each replay keeps its full original *tracking-file* SHA-256, not the hash
of its temporary selected-row CSV. The exact official `games.csv` and
`plays.csv` records are joined to derive `possession_team`,
`offense_side`, and the source-charted quarter, down, yards-to-go,
offense formation and personnel. The 3D viewer displays those fields in
a dedicated charting strip, explicitly **not** as inferred coaching tactics.

The source hashes are checked once before reading and again before the
batch directory is committed. The additional temporary filtered CSV
files are destroyed at the end of execution. The program does not grant
distribution, commercial use, live data access, or source-video alignment.

Some special teams entries have unavailable `down`, `yardsToGo`, or
`offenseFormation` metadata. These remain null and are displayed as
unavailable rather than guessed. The batch does require an explicit
home/visitor possession mapping for each selected play.

The four replay JSONs can then be multi-selected through **Load historical
replay JSON(s)**. If a local 177-play catalog is loaded, its play IDs can be
searched first, followed by exporting the selected play IDs using the
same batch command.


## Manifest-verified browser research session

In GameDay Lab, select **Load replay JSON(s) + optional manifest**. Select
`manifest.json` **and every JSON replay listed inside it**, together in the
same file-picker operation (at most 12 replay files plus the manifest).

The browser now re-computes SHA-256 of **each replay JSON's exact bytes**
using the platform Web Crypto API and compares each to `manifest.json`.
It also checks the manifest's play identities, possession, frame and source-row
counts, excluded-position counts, license declaration and metadata provenance.
Missing, extra, duplicated, tampered or semantically conflicting files reject
the **entire** import without changing the loaded library. Import still works
without a manifest, but the viewer clearly marks those standalone JSONs as
**not checked against an export manifest**.

**Trust boundary:** A self-supplied manifest and matching hashes establish
internal package consistency, *not* authenticity of NFL-source CSV files.
Only the offline Python exporter checks the whole pinned source CSV identities.
An attacker could replace the manifest and replay bytes together. The browser
does **not** claim official NFL certification, video synchronization, rights
approval, verified tactics or authorization to train models. All imports stay
in browser memory and are not uploaded by this workflow.

Run the frontend verification suite before merging:

    cd apps/gemini-fantasy-console
    npm run test:field3d
    npm run build

## Shared source charting contract

The game timeline, batch exporter, and historical replay parser now apply
consistent bounds: season 2000–2100, week 1–22, quarter 1–5, down 1–4 for
ordinary offensive downs, yards-to-go 0–100, and charted labels up to 120
characters. An official source down of zero (e.g., special teams) is
normalized to `null` in the replay because that is **not** an offensive down;
the game timeline retains its charted zero. Missing values are not guessed.

The synthetic Chromium smoke adds a local manifest/replay pair whose exact
replay SHA-256 must be verified by Web Crypto. Altering those JSON bytes
must reject the import atomically without altering the prior research
playlist. This fixture is deliberately synthetic and is **not** the real
2017 NFL data qualification.
