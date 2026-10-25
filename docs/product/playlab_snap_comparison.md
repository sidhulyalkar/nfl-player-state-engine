# Snap-aligned two-play research comparison

**Status:** draft experiment stacked on Play Lab Research Workspace v1 (PR #109).
It must not be interpreted as game-film alignment, coverage classification,
a causal impact estimate, or qualification of source-use rights.

## Behavior

Open any two different locally imported recorded plays from **the same game
and exact original tracking source SHA-256**. In the historical replay viewer,
select **Compare plays**. A new research workspace displays two independent
overhead field views on a single nominal clock measured from the first
source-recorded `ball_snap`, `snap`, or `snap_direct` event in each play.

The comparison is **unavailable**, with an explicit reason, when either play
has no recorded snap marker, the two selections identify the same play, or
the original game/source identifiers differ. We do not guess the snap from
motion or inferred player formations.

A comparison's usable nominal time range is the **intersection** of the two
play recordings after subtraction of their respective source snap times.
Players are not automatically matched across plays; the analyst explicitly
selects one entity in each view.

At every shared nominal time, we display the **most recent actual recorded
source frame** only during that frame's nominal 100 ms interval. If either
play is inside a skipped-source-frame window, its entire field is blank with a
missing-observation warning. There is no rendering of a last-known position
under a false "current" label. The second play can remain visible when the
first play has a gap.

The optional statistics are individual-play, observed-only descriptions:

- Straight-line field distance to that player's recorded snap position, if
  the entity was observed at snap.
- Field-space distance to the nearest recorded opposing player, if the entity
  and source-declared opponent sides were observed in that frame.
- Recorded source frame ID and nominal playback time.

They are **not** differences in player skill, workload, route efficiency,
defensive assignments, coverage, or play-level win probability. No opponent
identity is assumed across frames or plays. No source event is inferred.

## Tests

```bash
cd apps/gemini-fantasy-console
npm ci
npm run test:field3d
npm run build
```

The pure adapter suite `snapAlignedComparison.test.mjs` validates source
provenance, same-play rejection, missing snaps, snap-relative interval,
independent selected-entity geometry and lack of samples in frame gaps.

The synthetic Chromium workflow should also demonstrate two overhead
fields, nominal frame stepping and blank fields during missing source frames.
This is still **synthetic CI**. Real 12-play qualification remains a separate
offline task as described in `docs/product/playlab_private_qualification.md`.

## Open questions and limitations

- Should future comparison use identical positional roles across games?
  That is not supported by source observations alone; it needs a separately
  validated role mapping.
- Would the measured differences improve a fantasy forecast? Unproven.
  Follow normal train/validation/test separation, leakage checks and
  out-of-time ablation gates before model adoption.
- This viewer does not align recorded frames to official synchronized video
  or infer verified coverage.
