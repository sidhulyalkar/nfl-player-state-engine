# Google AI Studio prompt: Draft War Room

Import this repository into Google AI Studio Build mode and work inside the existing `apps/gemini-fantasy-console` React + Express application.

Your highest-priority task is to build a production-quality **Draft War Room** for the NFL Player State Engine. Do not replace the existing application architecture or create a disconnected toy app.

## Read these files first

Before modifying code, read:

- `docs/product/draft_war_room_frontend.md`
- `docs/modeling/draft_intelligence_models.md`
- `docs/product/live_draft_room.md`
- `docs/product/gemini_ai_studio.md`
- `apps/gemini-fantasy-console/README.md`
- `src/player_state_engine/fantasy/draft.py`
- `src/player_state_engine/integrations/portfolio.py`
- `src/player_state_engine/api/app.py`

Treat the Python Player State Engine as the numerical source of truth.

## Product objective

During a live fantasy draft, the user will often be deciding among 2 to 5 players. The interface must help answer four different questions:

1. Who has the best underlying football projection?
2. Who has the most value in this exact league format?
3. Who fits the user's current roster best?
4. Who must be selected now because he is unlikely to survive to the user's next pick?

Do not collapse these into one opaque answer. Show the component signals and then show the final room-aware recommendation.

## League formats

The product must support arbitrary settings from live platform snapshots, especially 2QB and superflex.

Never assume an 8-team league is shallow. A league with 8 teams, 2 QB, 3 RB, 3 WR, 3 FLEX and 1 TE has substantial starter demand.

Never use generic one-QB expert ranks as if their ordinal values transfer to 2QB leagues.

Live Sleeper / ESPN roster positions and scoring settings override fallback profiles when available.

## Required Draft War Room layout

### Persistent top bar

Show:

- active league selector;
- platform;
- compact format label such as `12T • 2QB • Half PPR • Median`;
- current pick;
- user's next pick;
- draft slot;
- snapshot freshness;
- projection freshness;
- model version;
- manual refresh.

Use a clear `LIVE`, `STALE`, `HISTORICAL`, or `SYNTHETIC DEMO` badge.

### My roster rail

Group drafted players by QB / RB / WR / TE / FLEX / bench.

For each position display:

- current count;
- target count;
- projected starters;
- positional need;
- depth status.

Make 2QB depth visually obvious.

### Available-player board

Required columns:

- live rank;
- player name;
- position;
- team;
- draft action;
- live draft score;
- q10 / q50 / q90;
- VORP;
- replacement rank;
- league starter demand;
- roster need score;
- tier-cliff indicator;
- market ADP;
- survival to next pick.

Support fast search, position filters, keyboard navigation and CSV export.

Selecting a row should add the player to the compare tray without navigating away.

### Room-state rail

Show:

- recent picks;
- positional run counts;
- remaining positional tiers;
- teams selecting before the user's next pick;
- their positional needs when available.

If opponent roster-need information is unavailable, omit it rather than infer it with Gemini.

### Candidate compare tray

Allow 2 to 5 players.

For each candidate organize data into five sections:

**Football**
- q10 / q50 / q90;
- availability;
- opportunity confidence;
- role-growth / breakout signals.

**League value**
- VORP;
- replacement rank;
- starter demand;
- scarcity / tier cliff.

**Roster fit**
- position need;
- likely starting slot;
- marginal starter value when available;
- post-pick depth.

**Draft timing**
- current pick;
- next pick;
- ADP;
- ADP uncertainty;
- survival to next pick;
- reach rounds.

**Team impact**
- only display simulator-produced values;
- if unavailable, label the section `MODEL NOT YET AVAILABLE` rather than estimating it.

At the bottom explicitly identify:

- Best raw projection
- Best league value
- Best roster fit
- Best pick now

They are allowed to disagree.

## API boundary

All authoritative calculations belong in Python.

The frontend may sort or filter server-returned rows, but it must not implement its own formulas for:

- VORP;
- replacement level;
- starter allocation;
- QB scarcity;
- roster-fit utility;
- tier cliffs;
- survival-to-next-pick;
- draft action;
- player projections.

Prefer dedicated Product API endpoints as they become available:

```text
GET  /v1/leagues/{league_id}/draft/board
POST /v1/leagues/{league_id}/draft/compare
```

If those endpoints are not yet implemented, use the closest existing Product API response and clearly mark missing live-draft dimensions. Do not recreate missing metrics in JavaScript.

## Live update behavior

The UI should support a conservative active-draft refresh loop:

1. request latest platform-backed league state from the Product API;
2. request the server-generated live draft board;
3. preserve the last valid board while the new request is in flight;
4. update the UI atomically;
5. cancel obsolete requests;
6. back off on repeated errors;
7. stop active polling after the draft ends.

Always include a manual refresh button.

Never hammer Sleeper or ESPN from the browser. Platform access belongs behind the server boundary.

## Gemini Copilot

Gemini is a read-only draft analyst and explanation layer.

Use Gemini function calling to retrieve deterministic data before making factual claims. Use structured output for the final comparison payload where appropriate.

Add or extend tools conceptually equivalent to:

- `get_league_context`
- `get_live_draft_board`
- `compare_draft_candidates`
- `get_player_detail`
- `get_my_roster`
- `get_recent_draft_picks`
- `get_model_evidence`

Do not give Gemini a tool that silently drafts a player or performs a fantasy-platform transaction.

A good user query is:

> “I am deciding between these three players. Compare their inherent value, how they fit my current roster, the positional scarcity if I pass, and how likely each is to return at my next pick.”

A good answer should distinguish evidence such as:

- highest projected player;
- highest VORP player;
- strongest roster fit;
- biggest tier cliff;
- lowest survival-to-next-pick probability;
- assumptions that could flip the recommendation.

Every answer should expose material uncertainty.

## Gemini safety / grounding rules

Gemini must not:

- invent a projection;
- invent live draft picks;
- invent ownership;
- invent an injury or news item;
- calculate replacement value itself;
- make up an ADP value;
- overwrite stale data with a plausible guess;
- claim a custom model exists before the Python artifact exists;
- fine-tune itself and call that the fantasy model.

If a required field is missing, say so.

## Model architecture boundary

Custom trained fantasy models live in Python, not in the React / Gemini layer.

The roadmap includes:

- availability / participation model;
- position-specific opportunity heads;
- conditional efficiency model;
- weekly and season distribution simulator;
- QB starter-security model;
- deterministic replacement / scarcity engine;
- empirical draft-survival model;
- roster marginal-value simulator;
- later opponent-room positional hazard model.

The UI should be designed so these models can be added without redesigning the product.

## Design direction

Keep the existing dark analytical identity, but make the Draft War Room faster and less dashboard-like than the research pages.

Use:

- crisp typography;
- compact tables;
- aligned numerical comparison;
- small distribution plots;
- tier separators;
- scarcity bars;
- before / after roster deltas;
- restrained motion when a new pick changes the board.

Avoid:

- decorative radar charts;
- giant KPI cards;
- excessive gradients;
- chat-first layouts that hide the draft board;
- green/red coloring without text or icons;
- animations that distract during a running draft clock.

Desktop is primary. Make the compare tray usable on a laptop at draft time. Mobile should still support roster view, player search, compare and refresh.

## Build sequence

Implement in this order:

1. make sure the existing app builds without regressions;
2. add the Draft War Room route and navigation;
3. build format / freshness header;
4. build roster rail;
5. build available-player table from existing API data;
6. build candidate compare tray;
7. build room-state rail;
8. wire server-side refresh behavior;
9. add Gemini comparison tool routing;
10. add robust loading, stale and error states;
11. test 12-team 2QB half-PPR median and 8-team expanded 2QB PPR fixtures;
12. verify the full production build.

Do not rewrite unrelated views while implementing this feature.

## Acceptance scenarios

Test at least these cases:

1. The top two players are both QBs in a 12-team 2QB league and QB replacement falls sharply behind them.
2. A high-ranked RB has a better raw projection, but the user's roster already has strong RB depth and zero QB2.
3. A WR is the best roster fit but has an 80% estimated chance to survive to the next pick.
4. A candidate is missing market ADP. The UI should show unknown timing rather than zero urgency.
5. Platform refresh fails after several successful picks. Keep the last valid board and display stale state.
6. Gemini is unavailable. The deterministic Draft War Room remains fully functional.
7. Projection data is unavailable. Do not silently fall back to fake live rankings.

Finish by running the existing frontend build and preserving the Python source-of-truth boundary.
