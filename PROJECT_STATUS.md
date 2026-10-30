# Fourth Down Lab: Project Status and Qualification Gates

> Status snapshot: 2026-10-29. Update this file only after checking live GitHub
> PR heads and workflow conclusions. **This is not a self-updating dashboard.**
> The default `main` branch is v0.17; research PRs below are not merged.

## Release branches and dependency order

| Layer | PR | Target | Last known validation | Production authority |
| --- | --- | --- | --- | --- |
| v0.17 fantasy application, forecasts and release controls | main | - | Published baseline documentation; current champion deployment not confirmed here | Depends on actual approved local artifacts and fresh source snapshots |
| Historical Play Lab composition | #109 | main | Synthetic full CI green at `9fe5932` | Research only |
| Snap-relative two-play comparison | #113 | #109 | Synthetic full CI green at `023655f` | Research only |
| Rights-aware AngleIQ v1 | #114 | #113 | Synthetic full CI green at `0420796`: 601 Python, 85 frontend tests plus Chromium | Research only |
| Reproducible private pilot/release preflight | #118 | #114 | New CI result must be checked before marking pass | Research only |

The historical tracking/AngleIQ chain must be reviewed **from its base upward**.
A pass on #118 is not permission to merge the stack without external
source/media qualification. A PR head or base change invalidates the last
recorded CI conclusion until the new exact composition is checked.

## Scientific authority layers

1. **Historically benchmarked:** numerical weekly quantiles (2021-2025
   out-of-sample), position-specific carries correction, and direct preseason
   scoring contracts with frozen multi-season results. See
   `docs/benchmark_real_2020_2025.md` and
   `docs/modeling/direct_league_score_preseason.md`.
2. **Format-specific production boundary:** PPR season distribution;
   half-PPR season `q50_only`; median game-week policy unqualified;
   special teams `external_market_only`. A release also needs source
   freshness, league fidelity and immutable approved champion. See
   `DRAFT_DAY.md`.
3. **Research only:** Player State Graph 2.0, new game-world-model terminal
   families, official/news/persona challengers, historical tracking/Play Lab,
   two-play comparisons and AngleIQ video analysis. Negative experiments stay
   negative. See `docs/modeling/current_week_official_availability_v3_result.md`.
4. **Software evidence is not scientific evidence:** lint, unit tests, a
   production build and Chrome smoke cannot prove accuracy of original
   tracking positions, video alignment, player tactics, clip copyrights or
   incremental fantasy prediction value.

## P0: complete offline 12-play BDB source qualification

- [x] Pinned-source verifier, source catalog, multi-play exporter, hash manifest,
      browser SHA/semantic import, 2D/WebGL2 missing-frame display.
- [x] Mac-portable deterministic selection from full metadata-only audited
      source catalog, with diverse source quality and reference cases.
- [x] Tight source identity, license, metadata provenance and gap accounting
      preflight for the selected local batch.
- [ ] On authorized private machine, obtain the exact three pinned original
      CSVs and independently check actual use terms.
- [ ] Run `scripts/build_bdb2019_play_catalog.py`,
      `scripts/select_bdb2019_pilot.py`,
      `scripts/export_bdb2019_replay_batch.py --selection-file`.
- [ ] Run Chromium `PLAYLAB_REAL_SESSION_DIR` qualification with 12 files,
      compare time/memory, inspect longest/highest-gap plays and 2D fallback.
- [ ] Preserve a **redacted**, location-safe local report with original-source
      digest, selection digest, browser version, resource use, gaps and reviewer
      sign-off. Do not commit copyrighted tracking or media.
- [ ] Independently review license and source terms for any contemplated
      publication, redistribution, model training or commercial reuse.
- [ ] Investigate discrepancies before merging PRs #109/#113/#114/#118.

The selector is a *technical smoke sample*, not a randomized scientifically
representative sample. The browser digest matches a declared manifest; it
cannot independently authenticate the NFL CSV without the offline verifier.

## P0: 2026 prospective and decision evaluation

- [ ] Verify the exact currently mounted champion, release status and real
      connected league snapshots under `check_draft_checkout.py --strict-data`.
- [ ] Freeze real pregame prediction snapshots with prediction-time evidence,
      opponent/league contract and immutable hash.
- [ ] Settle only after outcomes; retain missing predictions, late arrivals and
      all failed recommendations in the denominator.
- [ ] Compare player calibration, pinball loss, interval sharpness and
      positional error against transparent baselines, not only expert ranking.
- [ ] Freeze actual lineup/waiver/trade decisions *before* results; compare
      action value, acquisition costs, roster legality and counterfactual
      regrets across the supported league profiles.

Source health and champion identity are separate from accuracy. A negative
prospective result must remain visible; no discretionary retrospective
projection edits.

## P1: licensed AngleIQ and comparative geometry study

- [ ] Obtain independently rights-cleared, synchronized football footage
      sufficient for local annotation and analysis (not merely a subscription
      to a video viewer).
- [ ] Run `build_angleiq_manifest.py`, then the offline scene-candidate
      scanner, SHA-verified local AngleIQ browser view and manual anchor audit.
- [ ] Measure video↔video and video↔tracking event alignment error and
      explicitly report all unresolvable clips.
- [ ] Label ball, boundary, contact, clarity and occlusion with independent
      reviewers, comparing Top-3 ranking to fixed-camera/random baselines.
- [ ] Only promote a tracking/video-derived forecasting feature after
      timestamp-safe, held-out paired ablations with negative controls.
- [ ] For any live camera deployment, obtain a licensed multi-feed provider;
      a single broadcast or public highlight page cannot expose unseen cameras.

## Project operating commands

```bash
# Fresh checkout / functional build
python -m pip install -e '.[dev,api,intelligence,espn]'
cd apps/gemini-fantasy-console && npm ci && npm run build && cd ../..
pytest -q
python scripts/check_draft_checkout.py

# Production-use readiness requires current local data:
python scripts/check_draft_checkout.py --strict-data

# Private research pilot: exact commands and terms gate:
# docs/product/playlab_private_qualification.md
```

Use GitHub issue #108 for Play Lab qualification actions, PRs #109/#113/#114
for the existing research layers, and PR #118 for the private pilot/release
preflight. Do not declare the release complete until each gate is independently
checked with the appropriate real evidence.
