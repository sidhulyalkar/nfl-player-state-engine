# 3D Play Lab: lightweight WebGL2 field (initial operational implementation)

Branch: feat/playlab-3d-integrated (PR #92), now based directly on main after PRs #89 and #90 merged. Original stacked PR #91 superseded.

## Shipped capabilities

- Real WebGL2 render surface with **120 by 53.3 yard** mesh field and real 3D player cylinders/helmets.
- Physical depth, yard markers, end zones and a free camera with **broadcast,
  elevated All-22 and overhead** presets.
- Orbit drag, shift/right-drag pan, scroll/pinch-device wheel zoom, explicit zoom/reset buttons.
- Overlay canvas for jersey IDs and yard labels. Click a player to inspect its
  recorded source identity; keyboard-safe player selector remains in the sidebar.
- Historical playback sources use observed x/y at **each recorded frame**. Frame
  IDs, source events and timestamps remain authoritative; frame gaps are **not**
  interpolated, and each continuous observed trail is bounded to consecutive
  frame pairs only.
- Snapshots can show movement trails, team colors, and a geometric nearest
  opponent line for roles with source-confirmed offense and defense sides.
- **Snap formation:** only if a recorded frame has an explicit ball_snap, snap,
  or snap_direct source event, the user can jump directly to it, overlay ghost
  rings at its recorded player positions, and inspect selected-player straight-
  line displacement since snap. No phantom presnap alignment is created when
  the source omits a snap event. These rings do not classify defensive coverage.
- Pure frame-join tests ensure movement trails never bridge missing frame IDs.
- No ball height is inferred from 2D tracking. Ball is drawn on/near the ground
  and labeled **height unknown**, NOT on an invented throw trajectory.
- WebGL2 unavailable/context loss -> return to existing working SVG 2D mode.
- The pre-existing demo scenarios have an explicitly labeled 3D **illustration**
  mode. They do not become licensed NFL plays by being in WebGL.
- Pure camera math, historical input schema and gap-safe motion helpers are independently
  tested in Node; frontend CI runs the geometry, tracking and replay-contract
  test suites after the TypeScript/Vite production build.
- **Measured movement vectors** are derived only from two temporally and numerically
  adjacent recorded frames, and have separate labels from source-reported speed.
  Optional acceleration is shown only when present in the source.
- **Observed team footprint** reports width (max y minus min y) and depth
  (max x minus min x), both in yards, for source-confirmed offense/defense sides.
  These are geometry, not an automated personnel or coverage classification.
- Source-file imports fail closed on duplicate NFL IDs, malformed numeric measurements,
  invalid source labels or corrupt frame identifiers. Kaggle-style NA identifiers
  for the ball and absent optional speeds/orientations are handled separately.

## Usage

1. Open Fourth Down Lab, select GameDay Lab.
2. Select 3D Field, adjust camera preset; orbit, pan and zoom.
3. Synthetic scenarios can replay immediately and are prominently labeled.
4. For genuine observed movement, import an authorized NFL Big Data Bowl
   tracking CSV with scripts/import_bdb_tracking.py and load the resulting
   HISTORICAL_RESEARCH replay JSON in the GameDay Lab.
5. Select a player by field click or keyboard-accessible player selector.
6. Toggle nearest opponent, observed trails and jersey numbers.
7. Select 2D Field any time as the lightweight alternative.

## Source and engineering boundaries

- Historical source is user-supplied, never publicly hosted by this patch.
- Fetching the complete official public 2017 sample was not possible from the
  available runtime; actual file playback, screenshot and cross-browser
  validation remain unverified. Passing synthetic/fixture tests is not the same
  as validating an NFL replay against its source footage.
- Exact coach calls and defensive coverage assignments are not observable
  from x/y alone, and no fabricated tactical labels are generated.
- Direct WebGL2 avoids new npm dependencies, keeps the RedZone Companion
  lightweight and prevents unwanted background video/GPU load.
- WebGL visuals are not a 3D full-motion avatar or licensed Madden animation.
  The models are stylized field markers with true 3D geometry and scale.
- Geometry input from public tracking is already validated by the replay
  parser, with an additional bounds check in the renderer.
- Rendering draws only on observable state/camera/viewport changes. It does
  not run a permanent draw loop when the replay is paused.
- Raw source file rights, source attribution and any commercial deployment
  need independent review; the renderer grants no data redistribution rights.

## Testing and next qualification

    cd apps/gemini-fantasy-console
    npm ci
    npm run build
    npm run test:field3d

    pytest -q tests/product/test_gameday_tracking.py tests/product/test_gameday_legacy_tracking.py

Review a real 2017 source replay against source-aligned video after legal
review. Capture screenshots for every preset, zoom, selection, and frame-gap
case. Test Safari, Firefox, Chrome, high-DPI and GPU-disabled fallback.
Measure frame timing on older laptops and multi-monitor use.
No web browser render test or actual tracking CSV has been performed in this PR.

## Next research stages

- Move to an instanced-marker render path if >22 animated objects or many
  simultaneous fields are required; avoid keeping dozens of live WebGL contexts.
- Add verified play metadata (home/away, down, distance, personnel, formation,
  documented source event identities) by direct play ID joins, never heuristic
  guesses.
- Historical coverage/route classifications require human validation and
  error calibration; show estimates only as estimates.
- Add true positional tracking and video alignment only with explicit rights.
- Preserve the live multi-game RedZone Companion as scoreboard and alerts,
  with **one optional** featured 3D replay rather than 8+ concurrent canvases.

Technical references: https://threejs.org/docs/pages/WebGLRenderer
and https://github.com/nfl-football-ops/Big-Data-Bowl/blob/master/schema.md.


## Precision replay timeline (next tranche)

- Historical replay supports 0.25×, 0.5×, 1× and 2× playback, with a
  hundredth-second scrub control and explicit previous/next **recorded**
  frame buttons.
- A missing frame is no longer silently presented as current position.
  During the source gap, current 3D and SVG player/ball positions are hidden
  and a status identifies the last recorded frame. Last-observed information
  in the inspector is explicitly identified as such.
- Selected player trails remain composed solely of observed adjacent-frame
  samples, with no bridge drawn across missing frame IDs.
- Frame stepping jumps directly between source IDs, even when multiple
  intervening frames are missing.
- Node tests validate missing-frame detection and frame stepping at nominal
  10 Hz, including exceptional timing inputs.
- This is a local historical research viewer; playback speed controls do
  **not** create live tracking or represent interpolation between samples.

A future pass should add visual snapshot testing in Chromium/Firefox/Safari,
versioned graphics contracts, and a source-authenticated full 2017 sample.


## Motion evidence and refined marker silhouettes

The 3D actor rendering now uses low-poly, symmetric football silhouettes
(padded torso, sleeves, legs, boots and helmet) instead of a single cylinder.
The actor pose is explicitly **neutral**. Do not interpret the helmet or
torso as the player's observed facing angle.

A separate ground chevron appears only where consecutive source x/y samples
support a finite, plausible movement vector. The direction is **derived
travel heading** and is not interchangeable with player facing, gaze, an
assigned route or defensive coverage. No chevron appears for stationary,
missing, nonfinite or implausible movement, or if the entire glyph would leave
the playing field. The 3D source badge reiterates the distinction when
chevrons are visible.

The official 2019 Big Data Bowl schema supplies an angle of **motion**
(dir), but not the same explicit player orientation field offered in later
Big Data Bowl releases. This implementation deliberately does not apply a
shared angle-to-world transform to both fields. A future verified
source-specific convention contract would be needed for a truthful player
facing overlay.

Longer historical replays no longer rescan all previous frames to calculate
one player's path length at each timestamp. A precomputed per-player
path-prefix index preserves gaps and identity changes, making UI reads O(1).

### Browser regression scope

The GitHub Actions Chromium smoke additionally uploads a clearly
labelled **CI-generated fake tracking JSON** through the real import control.
It verifies transition to the historical UI, source labels, jump to a
recorded source frame, travel provenance, and stepping across absent frame IDs.
This fixture is not an NFL recording, does not authenticate the data
pipeline's published source rights, and must not be used for scientific
or product claims.

Actual first-party 2017 tracking-file animation and video alignment,
multi-browser screenshots, and frame-time performance measurement are
separate remaining qualification gates.

Official historical source dictionary:
https://github.com/nfl-football-ops/Big-Data-Bowl/blob/master/schema.md
