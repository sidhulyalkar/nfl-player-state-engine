# Google AI Studio prompt: Draft War Room v0.9

Import this repository into Google AI Studio Build mode and work inside the existing `apps/gemini-fantasy-console` React + Express application.

The Draft War Room is already operational. Your job is to preserve and refine it as a production-quality decision surface. Do not replace the architecture, rebuild numerical logic in JavaScript, or create a disconnected toy application.

## Read these files first

Before modifying code, read:

- `README.md`
- `docs/product/draft_war_room_frontend.md`
- `docs/modeling/draft_intelligence_models.md`
- `docs/modeling/ranking_calibration_v09.md`
- `docs/modeling/draft_survival_training.md`
- `docs/data/ranking_and_news_sources.md`
- `docs/product/live_draft_room.md`
- `docs/product/gemini_ai_studio.md`
- `apps/gemini-fantasy-console/README.md`
- `src/player_state_engine/fantasy/scoring.py`
- `src/player_state_engine/fantasy/valuation.py`
- `src/player_state_engine/fantasy/draft.py`
- `src/player_state_engine/fantasy/roster_simulator.py`
- `src/player_state_engine/fantasy/draft_planner.py`
- `src/player_state_engine/fantasy/rankings.py`
- `src/player_state_engine/integrations/portfolio.py`
- `src/player_state_engine/api/operational.py`

Treat the Python Player State Engine as the numerical source of truth.

## Product objective

During a live fantasy draft, the user commonly decides among 2 to 5 players. The interface must distinguish these questions:

1. Who has the best underlying football outcome distribution?
2. Who has the most value under this league's exact scoring and replacement economy?
3. Who creates the greatest marginal value on the user's current roster?
4. Who is most costly to pass because positional supply or the player himself is unlikely to survive to the next pick?
5. Where does the model disagree with external experts or markets, and how uncertain is that disagreement?
6. What does the unpromoted research lookahead say about the current pick plus the next turn?

Do not collapse these into one opaque answer.

## Mandatory epistemic boundaries

Keep these systems separate:

```text
football projection
league scoring and replacement value
roster marginal value
draft-room market timing
external expert and market calibration
research challengers
```

External consensus is not ground truth. A provider rank must never silently overwrite a model projection or `live_draft_score`.

A research challenger must never be presented as production merely because it produces a useful-looking number.

## League scoring correctness

The frontend must surface the Python scoring provenance when available:

```text
correlated_or_provided_league_quantiles
component_quantile_rescore
generic_points_fallback
```

If `league_scoring_fallback` is true or the league reports unsupported scoring keys:

- show a visible scoring-provenance warning;
- do not call the result custom-scoring exact;
- do not recalculate the missing scoring rule in the browser;
- do not ask Gemini to guess the adjustment.

The correct fix is to add the missing football component or scoring implementation in Python.

## League formats

Support arbitrary live roster/scoring settings, especially 2QB and superflex.

Never assume an 8-team league is shallow. An 8-team league with 2 QB, 3 RB, 3 WR, 3 FLEX and 1 TE has substantial starter demand.

Never use generic one-QB expert ranks as if their ordinal positions transfer to 2QB leagues.

Live Sleeper and ESPN settings are authoritative when available. Unsupported live rules must remain visible as provenance.

## Required persistent header

Show:

- league selector;
- platform;
- compact format label such as `12T • 2QB • Half PPR • Median`;
- current pick;
- next pick;
- draft slot;
- snapshot freshness;
- projection freshness;
- model version;
- scoring exactness or fallback state;
- manual refresh.

Use clear `LIVE`, `STALE`, `HISTORICAL`, or `SYNTHETIC DEMO` labeling.

## My roster rail

Group players by QB / RB / WR / TE / FLEX / bench and make 2QB depth visually obvious.

Show server-returned current counts and starter/depth context. Do not invent target counts or projected legal slots in React when Python has not returned them.

## Available-player board

Prefer columns that answer a decision:

- live rank;
- player;
- position/team;
- production draft action;
- production live score;
- unpromoted challenger score or rank when available;
- league-scored q10 / q50 / q90;
- VORP;
- replacement rank;
- league starter demand;
- tier cliff;
- positional supply;
- positional wait loss;
- ADP;
- survival to next pick;
- external consensus rank;
- model-versus-external delta;
- scoring provenance.

Selecting a row should add the player to the compare tray without navigating away.

## Dynamic scarcity

The board may expose:

- `position_supply_remaining`;
- `expected_position_drafted_before_next`;
- `expected_position_supply_next_pick`;
- `position_wait_value`;
- `position_wait_loss`;
- `draft_dynamic_scarcity_score`;
- `ranking_challenger_score`;
- `ranking_challenger_delta`;
- `ranking_challenger_promoted`.

The production `live_draft_score` and `draft_action` remain authoritative unless Python explicitly marks a challenger promoted.

Use the dynamic-scarcity fields to explain *why waiting is dangerous*, not to create a second unofficial ranking formula in React.

## Candidate compare tray

Allow 2 to 5 players.

For each candidate show the following groups.

### Football

- league-scored q10 / q50 / q90;
- availability;
- opportunity confidence;
- role-growth or evidence state when available.

### League value

- VORP;
- replacement rank;
- starter demand;
- dynamic scarcity;
- positional wait loss.

### Roster fit

- roster-fit score;
- likely legal starter slot;
- marginal floor / median / ceiling;
- starter probability;
- displaced player when applicable;
- depth delta.

### Calibration

- external expert consensus;
- expert dispersion;
- expert source count;
- market consensus ADP when available;
- model-versus-external rank delta.

Always label external values as calibration or market context, not model truth.

### Draft timing

- current pick;
- next pick;
- ADP;
- survival probability;
- expected positional supply next turn.

### Research lookahead

When `/draft/plan` is available, show:

- expected two-pick value;
- q10 / q50 / q90 two-pick value;
- expected next-pick value;
- likely next target;
- probability no preferred target survives.

This section must visibly say `RESEARCH`, `UNPROMOTED`, or equivalent unless the API explicitly says otherwise.

At the bottom explicitly identify:

- Best raw projection
- Best league value
- Best roster fit
- Best pick now

They are allowed to disagree.

## Ranking calibration

The API provides:

```text
GET /v1/rankings/sources
GET /v1/leagues/{league_id}/rankings/audit
```

Use these to expose:

- which external sources are installed;
- format match metadata;
- scoring exactness;
- consensus rank;
- expert dispersion;
- source count;
- model-versus-external disagreement;
- market ADP dispersion.

Do not convert consensus rank into `live_draft_score` in the browser.

Large disagreement should visually communicate:

> the model and outside information disagree, investigate the evidence.

It should not communicate:

> the model is wrong, move it to consensus.

## Room-state rail

Show:

- recent picks;
- positional runs;
- current and next picks;
- market-survival model source;
- scoring exactness;
- installed calibration-source count;
- stale/fresh state.

If opponent roster needs are unavailable, omit them rather than infer them with Gemini.

## API boundary

All authoritative numerical calculations belong in Python.

Core endpoints:

```text
GET  /v1/draft/leagues
GET  /v1/leagues/{league_id}/draft/board
POST /v1/leagues/{league_id}/draft/compare
POST /v1/leagues/{league_id}/draft/plan
GET  /v1/rankings/sources
GET  /v1/leagues/{league_id}/rankings/audit
```

The frontend may sort, filter, select, and visualize server-returned values. It must not implement its own formulas for:

- fantasy projections;
- custom league scoring;
- replacement levels;
- starter allocation;
- VORP;
- QB scarcity;
- roster marginal value;
- tier cliffs;
- draft survival;
- dynamic wait loss;
- production draft actions;
- ranking promotion decisions.

If the API does not expose a needed metric, extend Python instead of reproducing the formula in TypeScript.

## Live refresh behavior

Use the existing conservative refresh flow:

1. request current platform-backed league state;
2. request the server-generated board;
3. keep the last valid board while the request is in flight;
4. atomically replace state after success;
5. cancel obsolete requests;
6. back off after errors;
7. stop active polling when the draft ends;
8. refresh the ranking audit without blocking the production board.

Never hammer Sleeper, ESPN, FantasyPros, or another provider from the browser. Provider access belongs on the server or in offline data-ingestion jobs.

## Gemini Copilot

Gemini is a read-only explanation and orchestration layer.

Available draft-related tools include conceptual equivalents of:

- `get_live_draft_board`
- `compare_draft_candidates`
- `get_ranking_calibration`
- `plan_two_turn_draft`
- `get_league_context`

Rules:

- call deterministic tools before factual claims;
- distinguish production from research outputs;
- state when scoring uses fallback;
- explain external disagreement without treating it as truth;
- identify whether survival is empirical or fallback;
- expose material uncertainty;
- never make a fantasy-platform transaction.

The two-turn planner must never override the production `best_pick_now` result unless Python later promotes it.

## Evidence and news

Do not render every headline as equivalent evidence.

When evidence metadata exists, distinguish:

```text
OFFICIAL
DIRECT_OBSERVATION
REPORTED
COACH_QUOTE
PLAYER_QUOTE
ANALYSIS
SPECULATION
```

Prefer structured injuries, depth charts, snaps, participation, and opportunity data over free-text inference when both exist.

Never invent an injury, practice role, route share, or reporter claim.

## Design direction

Keep the dark analytical identity. The draft screen should be fast, compact, and number-forward.

Prefer:

- aligned numerical tables;
- compact fan/quantile displays;
- tier separators;
- positional-supply bars;
- before/after roster deltas;
- clear calibration badges;
- restrained motion when a new pick changes the board.

Avoid:

- decorative radar charts;
- giant KPI cards;
- chat-first layouts;
- consensus ranks visually dominating the production model;
- unlabeled research outputs;
- excessive animation during the draft clock.

Desktop is primary, but mobile should preserve player search, roster, compare, scoring provenance, and refresh.

## Acceptance scenarios

Test at least:

1. 12-team 2QB half-PPR: QB replacement becomes materially deeper than 1QB and the UI makes the supply consequence visible.
2. 8-team PPR with 2QB / 3RB / 3WR / 3FLEX: the league is not visually or numerically treated as shallow.
3. PPR versus standard with component projections: league-scored values change before VORP.
4. Generic fantasy-point artifact: scoring fallback is visibly labeled rather than called exact.
5. ESPN league with current `position_slot_counts` and `OP`: the UI shows the correct roster construction.
6. Large model-versus-expert disagreement: the UI highlights disagreement without moving the production rank.
7. Missing external rankings: the production draft product remains fully functional.
8. Strong WR likely to survive while a scarcer QB probably does not: compare timing and roster fit separately.
9. Research two-turn planner disagrees with production: production remains visually authoritative and research remains labeled unpromoted.
10. Platform refresh fails after successful picks: preserve the last valid board and show stale state.
11. Gemini is unavailable: deterministic draft and ranking-audit workflows still work.
12. Projection data is unavailable: do not fabricate live rankings.

Finish by running the production frontend build and preserving the Python source-of-truth and champion/challenger boundaries.
