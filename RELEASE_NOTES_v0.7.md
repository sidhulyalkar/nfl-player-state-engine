# NFL Player State Engine v0.7 — Draft Room

v0.7 turns the existing fantasy layer into a live, league-aware draft assistant for the 2026 season.

## Added

- dynamic starter allocation for arbitrary roster formats
- native 2QB and superflex scarcity
- arbitrary multi-FLEX demand instead of fixed FLEX-share assumptions
- league-specific replacement ranks and starter demand
- live snake-draft state and next-pick calculation
- ADP survival probability and reach/wait logic
- roster construction pressure
- positional tier-cliff detection
- median-scoring floor preference
- 12-team half-PPR median profile
- 8-team PPR 2QB / 3RB / 3WR / 3FLEX profile
- Sleeper username-level multi-league discovery and syncing
- Sleeper live drafts, picks and matchups in canonical snapshots
- optional ESPN integration using `espn-api>=0.46.0`
- multi-platform league portfolio configuration and snapshot persistence
- live draft board and league-sync scripts

## Corrected

The previous draft board subtracted `market_cost` directly from football utility. That mixed incompatible units when `market_cost` represented ADP. v0.7 keeps model value and market timing separate: model value answers *who is best*, while ADP survival answers *whether you need to take him now*.
