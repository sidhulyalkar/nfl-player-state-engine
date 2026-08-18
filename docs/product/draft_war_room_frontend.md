# Draft War Room frontend

## Product goal

The Draft War Room should answer a narrow question extremely well:

> Given the players still available, the rules of this exact league, the roster I have already drafted, and when I pick again, which player creates the most value for my team right now?

It is not a prettier consensus ranking page. The UI must expose the difference between **player quality**, **league-specific positional value**, **fit on the current roster**, and **draft timing**.

## What is live today

`build_live_draft_board()` is deterministic and safe to recompute after every pick. It removes drafted players, reconstructs the user's roster, updates roster needs, recalculates positional tier cliffs, computes the next snake pick, and updates the probability each player survives to that pick.

The current workflow is pull-based:

1. refresh the Sleeper or ESPN league snapshot;
2. rebuild `DraftState` from the snapshot;
3. rerun the live draft board;
4. render the new board.

The React application does not yet continuously perform that loop. The frontend implementation should add a conservative polling/manual-refresh layer and recompute only from fresh server data. A stale-data badge must remain visible whenever the platform snapshot or projection artifact is older than the configured freshness threshold.

## The central interaction: candidate compare tray

The primary draft interaction should be selecting 2 to 5 available players into a persistent comparison tray. The comparison should not collapse everything into one score.

For every candidate show these dimensions separately:

### 1. Football projection

- season q10 / q50 / q90;
- weekly floor, median and ceiling when available;
- availability probability;
- opportunity confidence;
- role-growth and breakout signals;
- model version and prediction timestamp.

This answers: **How good is the football projection?**

### 2. Inherent league value

- VORP versus the league-specific replacement player;
- replacement rank at the position;
- estimated league-wide starter demand;
- positional rank among still-available players;
- tier-cliff severity immediately behind the player;
- scarcity percentile.

This answers: **How expensive is it to replace this production in this league?**

This is especially important in 2QB formats. A quarterback does not become valuable merely because the QB position has high raw fantasy points. He becomes valuable when two required QB starters per team consume enough of the usable QB pool that replacement production falls sharply.

### 3. Fit on my roster

- roster need score;
- projected starting slot the player would occupy;
- whether the player upgrades a current projected starter or only adds bench depth;
- marginal starter points added;
- marginal floor and ceiling added;
- redundancy / concentration warning;
- bye-week overlap where relevant;
- post-pick position depth.

This answers: **What changes about my team if I draft him?**

The frontend should eventually display a small before/after roster diagram rather than only a number.

### 4. Opportunity cost of passing

- next pick number;
- market ADP and ADP uncertainty;
- probability the candidate survives to the next pick;
- expected quality of the best replacement player likely available at the next pick;
- current positional tier depth;
- number of managers between picks with an obvious need at the position, when roster-state data is available.

This answers: **Can I wait?**

### 5. Team-level season impact

This is the next modeling layer and should be clearly labeled experimental until validated:

- expected weekly starter points after the pick;
- median-game win probability;
- head-to-head win probability distribution;
- playoff qualification probability;
- championship probability;
- injury-resilience / depth score.

This answers: **Which player improves the roster outcome distribution, not just his own projection?**

## Recommended desktop layout

### Top bar

- league switcher for all connected leagues;
- platform badge;
- scoring and roster summary such as `12T • 2QB • Half PPR • Median`;
- current pick and next pick;
- live/snapshot freshness indicator;
- model version;
- manual refresh button.

### Left rail: my roster

Show drafted players grouped by QB / RB / WR / TE / FLEX / bench. Mark projected starters and display position depth against target roster construction.

### Center: available player board

Default columns:

- live rank;
- player;
- position;
- draft action;
- live draft score;
- VORP;
- replacement rank;
- roster fit;
- tier cliff;
- survival to next pick;
- q10 / q50 / q90.

Clicking a player adds him to the comparison tray. Keyboard shortcuts should make this fast during an active clock.

### Right rail: room state

Show:

- recent picks;
- positional runs;
- remaining starter demand by position;
- teams picking before the user's next selection;
- their current positional needs when available;
- current tier depletion.

### Bottom drawer: compare candidates

For 2 to 5 selected players show a radar-free, number-forward comparison. Prefer aligned rows, small distribution plots and before/after deltas over decorative charts.

The final row should answer four separate questions:

- **Best raw projection**
- **Best league value**
- **Best roster fit**
- **Best pick right now**

These may be four different players. That disagreement is useful information, not a bug.

## 2QB / superflex behavior

All draft surfaces must derive quarterback value from the actual league economy.

Required checks:

1. Count mandatory QB and superflex starter seats.
2. Estimate how many quarterbacks become weekly starters league-wide.
3. Calculate replacement production after those seats are filled.
4. Display the drop from the current QB to the next tier.
5. Distinguish QB1, QB2 and emergency QB3 roster value.
6. Penalize blindly stockpiling quarterbacks once the roster has sufficient depth unless trade value or an exceptional tier break justifies it.
7. Never import one-QB expert rankings as if their ordinal ranks were valid in 2QB leagues.

Consensus ranks and ADP are market features only. They must not be the target used to define player value.

## Live refresh contract

The frontend should use this loop while the draft is active:

```text
platform snapshot
    -> canonical LeagueSnapshot
    -> league_config_from_snapshot()
    -> DraftState
    -> fresh projection artifact
    -> build_live_draft_board()
    -> candidate comparison payload
    -> React render
```

The authoritative computation belongs in Python. Node may proxy/cache responses. React may sort/filter already-returned data but must not recreate VORP, scarcity, replacement levels, roster-fit utility or draft-survival logic independently.

Recommended UI behavior:

- auto-refresh while the draft is active using a conservative interval;
- refresh immediately when the user presses the button;
- stop aggressive polling when the draft is paused or completed;
- cancel obsolete requests when a newer refresh starts;
- keep the last valid board visible if a platform enrichment call fails;
- mark the board stale rather than replacing it with fabricated data.

## Candidate comparison API contract

The target Product API should expose a read-only endpoint conceptually equivalent to:

```text
POST /v1/leagues/{league_id}/draft/compare
```

Request:

```json
{
  "roster_id": "4",
  "draft_slot": 5,
  "player_ids": ["player_a", "player_b", "player_c"]
}
```

Response should include:

```text
league settings + provenance
current pick / next pick
candidate rows
raw projection dimensions
league-value dimensions
roster-fit dimensions
market-timing dimensions
post-pick roster deltas
reason codes
```

Until this endpoint exists, the UI may consume a full server-generated live board and select the requested rows client-side. It must not synthesize missing dimensions.

## Gemini copilot behavior

Gemini is the explainer and query router, not the scoring engine.

A good interaction is:

> “I am between these three players. Compare the cost of passing on each, how each changes my starters, and tell me which assumptions could flip the decision.”

Gemini should call deterministic tools, compare their returned fields, and produce a concise explanation such as:

- Player A has the best median projection.
- Player B creates the largest league-specific value because the QB replacement cliff is steep.
- Player C fits the current roster best but has a high probability of surviving to the next pick.
- Therefore Player B is the strongest pick now, unless the manager intentionally accepts QB scarcity risk.

Gemini must never invent injuries, ADP, projections, roster ownership, or live draft picks.

## Definition of done for the first War Room release

The first frontend release is useful when it can:

1. switch among all connected leagues;
2. derive each league's actual scoring and roster settings;
3. show the current pick, next pick and all completed picks;
4. refresh a server-generated live board;
5. compare 2 to 5 available players;
6. show raw value, scarcity, fit and timing independently;
7. make 2QB scarcity visible and explainable;
8. preserve provenance and stale-data warnings;
9. let Gemini explain deterministic results through tool calls;
10. remain fully usable without Gemini when the API key is absent.
