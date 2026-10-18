# GameDay Intelligence: product and research specification

Status: **initial GameDay UI and user-supplied historical research replay import on feat/gameday-intelligence-lab**. No live NFL ingestion, no independent license verification, no validated ratings.

## 1. Product intent

Keep a compact GameDay companion open next to live NFL/RedZone and fantasy tabs. Answer four questions without requiring the user to watch every play:

1. What happened?
2. Why did this play probably work or fail?
3. Which positions/players materially influenced the result, with what uncertainty?
4. What changes in team strategy, projected usage, fantasy lineup decisions, or rest-of-game outcomes?

The first release must be useful with play-by-play alone. High fidelity tracking and full 3D are optional capabilities, not prerequisites for showing truthful content.

## 2. The existing codebase

Build on:
- React + TS: apps/gemini-fantasy-console/src/OperationalApp.tsx
- NFL news/roster event state: NflHubPortal and nfl_hub_routes.py
- Existing research-only play-call / outcome models: game_intelligence_routes.py
- Authoritative projection, league and decision logic: FastAPI Player State Engine
- Immutable, point-in-time and source-authority design principles in AGENTS.md

GameDayLab contains a **deterministic synthetic teaching surface**: three play types, 22 position markers, replay scrubber, alternate projected camera views, routes, movement, point events, and evidence warnings. It is a projected SVG field, NOT a Three.js geometry engine or measured NFL replay. Names, scoreboard and event outcomes are fictional. Do not wire its invented frames or results into forecasts, API snapshots, or grades.

An adjacent **HistoricalReplayPanel** renders authorized, locally supplied Big Data Bowl 2025 recorded coordinates in the same workspace, with observed trails, frame-gap reporting, IDs, a scrubber and event tags. This is a separate `HISTORICAL_RESEARCH` mode, not the simulated football play. The JSON upload remains local to the browser; it is not pushed to a server.

## 3. Data sources / access

| Source | Candidate data | Update properties | Rights / hazards |
| --- | --- | --- | --- |
| NFL Next Gen Stats website | Public highlight illustrations and published advanced metrics | NGS statistics can lag until next day | No claim of a downloadable 2026 x/y API. NFL terms prohibit systematic collection without consent. Do not harvest private endpoints. |
| NFL Pro | Box scores and play by play | Described as live by NFL | Live display does not convey republication/API license. Confirm permitted access. |
| nflverse / nflfastR | Historical PBP, EPA, win probability, rosters, NGS aggregate stats | PBP updated on game days and nightly; weekly NGS updates nightly | Check license and attribution per dataset/source. Not a reliable seconds-level live replay feed. |
| FTN charting via nflverse | Formation, personnel, play context where supplied | Released after game, not true live | Observe the FTN CC BY-SA 4.0 requirements. |
| Big Data Bowl 2025 | Historical full tracking x/y/orientation, play events, player_play and formation | Static contest sample | Use for research, interaction development and replay validation subject to contest terms. |
| Big Data Bowl 2026 Prediction | Public 2023 tracking of selected passing-play segments | Static contest sample | Published CC BY-NC 4.0, not default commercial training rights; narrow task coverage. |
| Sportradar NFL official API | Licensed real-time game PBP and play events | Docs cite 3-second live cache TTL | Requires provider account/key/contract; PBP does not imply full positional tracking rights. |

Review: https://nextgenstats.nfl.com/highlights/play/type/team/2026/week/playerId/2026101809/553

Never equate a highlight URL or on-page animation with raw frame access, predictable update cadence, NFL media rights, or the right to reconstruct/resell the feed. Prefer official/licensed provider integration over web scraping.

## 4. Proposed API contracts (not implemented)

GET /v1/gameday/games?season=2026&week=7
GET /v1/gameday/games/{game_id}/plays?cursor=...
GET /v1/gameday/games/{game_id}/plays/{play_id}/replay
GET /v1/gameday/games/{game_id}/player-grades
GET /v1/gameday/games/{game_id}/tactical-summary
GET /v1/gameday/stream?games=... [SSE or WebSocket; authenticated, rate-limited]

All response envelopes MUST carry:
- schema_version, source, legal_use_profile and rights_status
- season, week, game_id, play_id and stable provider key mapping
- observed_at_utc, provider_published_at_utc, ingested_at_utc, rendered_at_utc
- event_version, corrected_from and whether the event is provisional
- data_mode: LIVE_LICENSED, HISTORICAL_LICENSED, HISTORICAL_RESEARCH, ILLUSTRATIVE_INFERENCE, SYNTHETIC_DEMO, UNAVAILABLE
- tracking_fidelity: RECORDED_FRAMES, SAMPLED_FRAMES, MODELLED_PATHS, FORMATION_ONLY, NO_TRACKING
- evidence_coverage and confidence/uncertainty by inferred field
- source_cutoff and model_version for generated in-game or rest-of-game predictions

If a field has no evidence, return null/unavailable; never fill in plausible fake player movement. Unverified predictions and any visual inferences must be clearly labeled on the *individual* play.

Proposed replay frame:
- t_seconds since snap, frame_id, event markers
- home/away and attacking direction
- ball {x,y,z?, possession?}
- players [{nfl_id, team, side, role, jersey, x, y, z?, speed?, orientation?, confidence?}]
- coordinates in yards, x=[0,120], y=[0,53.3]; orientation and field direction normalized *once*
- player/ball identity matching diagnostics, omissions, interpolated segments
- UTC event timestamps where available, replay monotonic timestamps for animation

Import of Big Data Bowl data needs an adapter for its exact game_id/play_id/nfl_id/frame_id contract, plus a separate terms-of-use confirmation. Joining Big Data Bowl games to nflverse requires verification of IDs (the 2025 competition notes old_game_id + play_id).

## 5. Rendering architecture

### Stage A: truthful 2.5D and tactical board [first UI slice]

- Project field-space coordinates into multiple viewing angles.
- Animation, scrub, pause, 0.5x/1x/2x speed, selectable layers.
- Formation cards: personnel, offensive alignment, *observed* defensive shell when possible.
- Overlays for routes, pressure, coverage, separation, passing windows ONLY when supported.
- Point events and alert feed. Explicit synthetic/demo labels.

### Stage B: full three-dimensional replay

Use React Three Fiber + Three.js with:
- 120 x 53.3 yard calibrated field mesh, proper endzones and yard markers
- instanced player avatars/markers, jersey/id labeling, player/team identification
- 3D ball parabola from measured release/arrival where available (otherwise illustrative)
- broadcast/isometric/All-22/overhead cameras; orbit and zoom; contextual fixed cameras
- interpolation under known sample rate, preserve real coordinates and avoid extrapolating across missing data without a watermark
- event timeline and video synchronization only if rights to media exist
- WebGL fallbacks: tactical SVG view, reduced motion, keyboard control, colorblind palettes, mobile/second-monitor modes

The projected SVG in the present branch is NOT the Stage B renderer.

## 6. Coaching intelligence: distinguish evidence from intent

Observable:
- offensive and defensive personnel (when charted)
- where players lined up and moved (when tracking available)
- play result, clock, down/distance, EPA/WPA change
- route type, pressure and coverage classifications (when sourced, with confidence)

Inferred:
- play family (inside zone, outside zone, mesh, flood, levels, etc)
- shell rotation, blitz, man/zone mix, disguised pressure
- QB progressions and option reads
- intended route distributions and blocking assignments

Unknown without privileged playbooks, film review, or interviews:
- the exact call, hot checks, audible intent, unobserved assignments, why a coach chose a play

UI language: 'looks consistent with Cover 3' (classification, confidence, evidence) rather than 'defense called Cover 3' when no authoritative charting exists.

Learn tendencies using only data that existed by the prediction cutoff. Compare play-call distributions and expected results conditionally on down, distance, score, clock, personnel, field position, opponent, weather, and prior usage. Analyze repeated sequence / counterfactual decisions against baselines. Prevent future play results leaking into pre-snap forecasts.

## 7. Player grading: proposed research model, not a shipped 10/10 score

Two distinct measures:
- **Play contribution**: ex-post estimated marginal value given context and teammates.
- **Player skill / repeatability**: shrunken multi-game estimate of stable contribution beyond context.

For play p and player i, conceptually:
  v(i,p) = E[team value | player action, known state, teammate and opponent actions]
           - E[team value | reasonable replacement action, same state].

Estimate only for roles supported by evidence. The replacement counterfactual is a *model* and its causal interpretation requires assumptions; avoid naive outcome crediting of all 11 players simultaneously.

Example attribution features:
- QB: pre-snap decisions, pressure-adjusted expected completion, throw placement, sacks versus throwaways, scrambles, turnover risk
- WR/TE: separation given matchup, leverage, route opportunity, catch probability above expectation, blocking
- RB: yards over expected, run-lane reading, tackle avoidance, receiving, pass protection
- OL: pressure allowed and created, double-team support, run-lane contribution, assignment uncertainty
- DL/EDGE: pressure generated, disruption timing, run fits, double-team value
- LB/DB: assignment-dependent coverage, closeness, tackling, run support, explosive-play prevention
- K/P/returners/coverage: kicking expectancy, field position, hang time, returns, lane discipline, penalties

Avoid grading OL, coverage defenders, receivers' unseen routes or uncredited blockers from box-score PBP alone.

Proposed grade pipeline:
1. Role-specific opportunity distribution under pre-play context.
2. Difficulty adjustment (opponents, leverage, coverage, separation, weather).
3. Execution deviation from expectations with multi-player attribution.
4. Shrink low-sample uncertainty via hierarchical priors.
5. Aggregate to position-specific standardized score, then monotonically map to [1,10] using historical calibration and comparable cohort distributions.
6. Publish number of eligible snaps, coverage completeness, interval, known exclusions and model version alongside score.
7. Human film-charting adjudication for disagreements; position-specific error and inter-rater reliability.

Do not use an arbitrary 10-point numerical mapping without longitudinal benchmark and interpretability evaluation. For uncertain in-game grades show "provisional" or "insufficient evidence", never confident decimals.

## 8. Live ingestion and notifications

Single provider adapter feeds normalized event bus:

provider polling/webhooks -> append-only event log -> versioned game/play store -> tactical inference / fantasy deltas -> source-aware SSE -> browser.

Required:
- Idempotent (provider,game_id,event_id,revision) keys; out-of-order buffering and replay-safe clocks.
- Corrections/retractions on revised scores, penalties and player attribution.
- Separate event time, receive time, ingestion lag, processing latency and browser staleness.
- Conditional alerts: touchdowns, turnovers, injuries (only confirmed claims), 4th-down choices, high-EPA/WPA swings, personnel usage, changes affecting user's starters/bench, sustained coverage mismatch.
- Dedup/rate-limit to prevent RedZone alert overload. User-configurable relevance and severity.
- Source outage/degraded state and manual refresh. Never hide stale dashboards with a green live badge.

No push/browser notification permissions without opt-in. For multiple games optimize fetch intervals and provider quota, and do not claim sub-10s latency without measurement.

## 9. Acceptance and research gates

UI correctness:
- Capture golden snapshots for overhead/broadcast/All-22 and each play scenario.
- Test all 22 markers are present, stable identities, and player positions stay in frame.
- Verify field x/y transform, left/right attack, endzones, time mapping and yards.
- Replay pause, scrub, speed, overlay toggles, event chronology; accessible keyboard input.
- Mobile and 2nd-screen display tested. UI demo source badge always visible.

Data:
- Contract fixtures from licensed provider; no protected page scraping.
- Verify game/play identifiers match across providers, including penalties/negated plays.
- Timestamp freshness and event revision reconciliation tests.
- Frame coverage, orientation, missing positions and interpolation limits measured.
- Explicit rights/attribution audit before public deployment.

Models:
- Frozen seasons/holdouts and point-in-time data cuts.
- Stratify by player position, down/distance, offense/defense, personnel and game situation.
- Baselines: simple EPA on-off, box-score, role/position prior, independent expert film charts.
- Test predictions and grade stability, uncertainty calibration, error correlations and adverse scenarios.
- Ablation for tracking, charting, and situational features; shuffled-player/time controls.
- No fantasy production promotion until the current champion wins frozen out-of-sample validation and improves fantasy decision regret.

## 10. Execution sequence

0. **Implemented this branch**: GameDay UI shell, three deterministic illustrative plays, historical BDB 2025 CSV normalizer, browser-local research JSON upload, recorded x/y playback and source-rights gates.
1. Refine typed replay schema, field coordinate golden screenshots, positional calibration, source coverage tests and provenance badges.
2. Exercise a real historical authorized tracking file (not just synthetic importer fixtures), audit motion, player IDs and per-frame coverage.
3. Add live PBP provider adapter under explicit licensed terms, notifications and multi-game command center.
4. Replace projected SVG with full Three.js camera/field/player system, retaining fallback.
5. Pilot role-specific play contribution benchmarks on charted data and only then surface validated 1–10 provisional grades.
6. Connect change signals to Sleeper/other league snapshots, rest-of-week distributions and fantasy decision deltas.

The source license review, provider credentials, streaming host, licensed tracking access, and real grading evidence are dependencies. This branch supplies none of those, and must not be described as a live NFL solution.

## 11. Using the historical local replay (implemented)

Get a local `tracking_week_N.csv` from the Big Data Bowl 2025 contest subject to its access/rights terms. Review license and permitted use. No dataset or player positions are redistributed in this repository.

```bash
python scripts/import_bdb_tracking.py \
  --csv /path/to/tracking_week_1.csv \
  --game-id YOUR_GAME_ID --play-id YOUR_PLAY_ID \
  --possession-team YOUR_OFFENSE_ABBR \
  --license-id "reviewed-source-terms" \
  --acknowledge-source-terms \
  --output /tmp/recorded-play.json
```

Open the modelling console, select **GameDay Lab**, and choose **Load historical replay JSON**. Select `/tmp/recorded-play.json`. The imported tracking frames, recorded events, source checksum, game/play IDs and missing-frame count will be displayed. Playback does not invent missing x/y positions or ball elevation. No coaching intent or player ratings are inferred.

The adapter currently targets only the **2025 BDB full tracking** camelCase schema, not the **2026 BDB prediction** pre-throw/post-throw segmented schema. Adapting the latter requires a separate explicit frame-offset and temporal synchronization protocol. This import does not train the Player State Engine or license a commercial product.
