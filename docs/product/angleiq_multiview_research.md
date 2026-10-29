# AngleIQ v1: local-first, rights-aware multi-angle research

## What is actually implemented

AngleIQ is a **manual-source, testable research workflow** attached to the
historical GameDay Lab viewer, not a live NFL video feed.

- Open a previously imported historical replay, then select **AngleIQ video angles**.
- Import one versioned JSON camera manifest for **that exact game/play**.
- Show all declared cameras, event questions, and human-reviewed visibility
  annotations. Compare **evidence visibility** and **highlight storytelling**
  rankings without asserting a ruling.
- For permitted local files, explicitly reconfirm user authorization, select the
  videos in the browser, and verify their **original bytes** against the SHA-256
  hashes in the manifest. They are played with browser-generated local blob
  URLs, not submitted to the API. Unverified files are not opened.
- For external references, show a link to the original HTTPS viewing page.
  Nothing downloads or embeds external streams.
- If a camera has at least two **manually supplied, normal-speed** time anchors,
  the featured video can seek to the corresponding event moment. Missing or
  incompatible anchors never trigger speculative synchronization.
- Display a ranked list only when at least 60% of the question-dependent
  dimensions have *human-reviewed* values. Unvalidated model annotations remain
  explicitly unranked.

**Evidence scores are view-visibility heuristics, not NFL grading, officiating
decisions, source authenticity certification, or prediction features.**

## Creating a manifest from local footage

1. Obtain footage you can legally inspect and process under the **actual**
   applicable rights. A streaming subscription does not automatically grant
   copying rights. Do not scrape NFL Pro, commercial streams, broadcasts, or
   DRM-protected material.
2. Install `ffprobe` from FFmpeg on your own machine.
3. Put local camera files in a **private directory**. Each supported source
   must be `.mp4` or `.webm`, no more than 40 MB; browser selections must
   total no more than 160 MB. For longer videos, use legitimately obtained
   and authorized short clips. AngleIQ does not perform downloading.
4. Copy the following example to `/private/angleiq-config.json`. Substitute
   the actual recorded game's ID, play ID, event timestamps, source permissions,
   camera names, filenames, and annotations. Do **not** treat these made-up
   examples as actual NFL source facts.

```json
{
  "schema_version": 1,
  "game_id": "2017090700",
  "play_id": "938",
  "tracking_source_sha256": "REPLACE_WITH_64_CHARACTER_ORIGINAL_TRACKING_SHA256",
  "rights": {
    "declaration": "REPLACE WITH REVIEWED AND APPLICABLE SOURCE TERMS",
    "local_playback_authorized": true,
    "derivative_analysis_authorized": true,
    "redistribution_authorized": false
  },
  "events": [
    {
      "id": "boundary",
      "event_time_s": 1.5,
      "label": "Landing",
      "question": "Does the camera show the feet, ball, and sideline?",
      "kind": "boundary_catch"
    }
  ],
  "angles": [
    {
      "id": "sideline_a",
      "name": "Recorded sideline angle A",
      "kind": "sideline",
      "source": {
        "type": "local_file",
        "filename": "your-authorized-angle.mp4"
      },
      "anchors": [
        {"event_time_s": 0.0, "media_time_s": 2.0},
        {"event_time_s": 3.0, "media_time_s": 5.0}
      ],
      "evidence": [
        {
          "event_id": "boundary",
          "provenance": "human_reviewed",
          "ball": 1.0,
          "boundary": 0.9,
          "control": null,
          "ground_contact": 0.9,
          "field_context": 0.4,
          "clarity": 0.8,
          "continuity": 0.8,
          "occlusion": 0.1,
          "note": "Replace these illustrative measurements with actual review."
        }
      ]
    }
  ]
}
```

The two sample anchors map one second of play-relative time to one second of
normal-speed video. **They are illustrative only.** Verify them independently
against the selected video before relying on synchronization. There is no
machine-fabricated snap, catch, or adjudication timestamp.

5. Generate a new metadata manifest, retaining the original video separately:

```bash
python scripts/build_angleiq_manifest.py \
  --config /private/angleiq-config.json \
  --media-dir /private/permitted-camera-footage \
  --output /private/angleiq-2017090700-938.json \
  --acknowledge-source-terms
```

The CLI reads the local video through FFprobe for duration and streams a SHA-256
digest. It never copies, uploads, publishes, transcodes, or modifies the video.
It rejects symlinks, directory traversal, invalid annotations, duplicate angles,
unreviewed processing rights, oversized media, unknown durations, incompatible
anchors, and an already existing output file.

In the Play Lab: load the matching **historical replay** first, open AngleIQ,
then import the generated `angleiq-*.json` file. Check the authorization box
and choose the local camera files. The browser independently verifies file
sizes, source names, and digests.

To reference an official viewer **without ingesting video**, use an angle with
`"source": {"type": "external_link", "url": "https://..."}` and empty
`"anchors": []`. Its external page opens separately via a click.
This does not imply that video is publicly downloadable, film-aligned, or
licensed for the local processing pipeline.

## Scoring and validation

The score for an annotated camera at a research question is a weighted sum of
observed visibility features. Positive dimensions count helpful visibility.
Occlusion is penalized; unknown dimensions lower score coverage. A separate
cinematic objective prioritizes clarity, scene continuity, and context.

Scores **do not** assess officiating correctness or video-truth confidence.
The available experimental metrics are:
- fraction of relevant dimensions actually annotated,
- reviewed versus unvalidated provenance,
- repeatability of source hashes and anchored time mapping,
- selected angle set and diversity of camera kind.

Future proof gates:
- multi-rater agreement on camera preference and visibility,
- accurate event-alignment error measured against human-verified frames,
- shot detection and camera-type classification against labeled media,
- time-to-decision and uncertainty calibration versus a fixed-angle baseline,
- licensed, locally repeatable source corpus with blinded holdouts.

No synthetic fixture, official tracking SHA, user-declared rights string or
browser blob URL establishes rights to redistribute or use videos for model
training. This module is not automatically fed into the fantasy prediction
engine.

## Development commands

```bash
cd apps/gemini-fantasy-console
npm ci
npm run test:field3d
npm run build
```

From the repository root, `pytest -q tests/product/test_angleiq_manifest.py`
validates source-side constraints without requiring FFprobe by stubbing the
duration probe in synthetic tests. Real CLI execution requires FFprobe.

The manifest's `tracking_source_sha256` must exactly match the imported historical replay's declared original tracking CSV digest. This is a consistency check, not independent authentication of NFL source bytes.

AngleIQ v1 is on a separate draft PR stacked atop the source-only Play Lab
integration. Do not merge either to main before the underlying real-source
qualification and relevant rights review are complete.
