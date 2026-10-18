# RedZone Companion: public source integration

## Implemented

- New Sunday / RedZone workspace tab with compact multi-game cards.
- GET /v1/gameday/sunday-board?season=2026&refresh=true on existing FastAPI.
- Public nflverse schedules/games.csv fetch with five-minute minimum refresh interval per process.
- Schema validation, atomic source snapshot, SHA-256 manifest, last-good fallback and stale warnings.
- Eastern kickoffs normalized to UTC, automatic closest-week choice, manually pinned favorite games.
- Optional in-page score-change feed. **These are published score deltas, not real-time verified scoring plays.**
- No fabricated game clocks, possessions, tactics, tracking frames or player grades.

## Local operation

Start the Python API using the existing project instructions and the Node/React client:

    python -m pip install -e '.[dev,api]'
    pse serve-product-api

    cd apps/gemini-fantasy-console
    npm ci
    npm run dev

Select RedZone Companion or navigate to ?workspace=sunday.
Cache folder is data/product/sunday_board/ by default; override with PSE_SUNDAY_BOARD_ROOT.
Public feed must be reachable. The separately bundled synthetic schedule file is never used for the public board.

## Source matrix

| Need | Source | Approx availability | Restrictions |
|---|---|---|---|
| Published NFL schedules/scores | nflverse schedules/games.csv | approximately every five minutes | Not authoritative real-time PBP/game phase |
| Coaching/fourth-down EPA/WPA baseline | nflverse PBP | after games, nightly or select game-day builds | Not a seconds-level feed |
| Play action, QB location, defensive box counts | FTN via nflverse | charted within roughly 48h | CC BY-SA 4.0 attribution |
| Weekly passing/receiving/rushing advanced metrics | NGS via nflverse | nightly | Not full tracking coordinates |
| Snap counts and depth charts | PFR/nflverse | daily | Not a reliable drive-by-drive role source |
| Historical player trajectories | Big Data Bowl datasets | static | contest-specific license, limited scope |
| Verified live PBP/clock/possession/player events | Sportradar or SportsDataIO | real time with contract and key | Paid access, licensing, quota |
| Live fantasy roster/matchup links | Sleeper read-only API | varying update cadence | Not a tracking or coverage source |

## Architecture for the next phase

License/credential gate -> server-owned provider poller -> immutable raw event store
-> revisions/corrections and identity normalization -> canonical game state
-> central SSE/WebSocket fanout -> low-noise RedZone UI and fantasy overlays.

Store provider game_id, play_id, event_id, version, provider timestamp,
receipt timestamp and source license. Debounce events and retract alerts
when penalized/corrected. Present source age prominently. Never claim that
a 3-second provider cache means a guaranteed 3-second real-world latency.
Live PBP does not provide true receiver/defender x/y tracking; schematic
motion must be labeled illustrative unless a licensed tracking feed exists.

## Licensing

nflverse-data publishes CC BY 4.0. Upstream rights for some source data,
commercial reuse and trademarks require a separate review. FTN charting
has CC BY-SA 4.0 terms. NFL.com restricts systematic website retrieval
without prior consent. Do not scrape Next Gen Stats private endpoints.

Sources:
- https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html
- https://nflreadr.nflverse.com/articles/dictionary_schedules.html
- https://github.com/nflverse/nflverse-data/releases/tag/schedules
- https://nflreadr.nflverse.com/reference/load_ftn_charting.html
- https://nflreadr.nflverse.com/reference/load_nextgen_stats.html
- https://developer.sportradar.com/football/reference/nfl-play-by-play
- https://sportsdata.io/developers/api-documentation/nfl
- https://support.nfl.com/hc/en-us/articles/35869706651156-NFL-Pro-FAQ-s-and-Answers
- https://www.nfl.com/legal/terms/

## Validation

Run pytest tests/product/test_sunday_board.py, existing full pytest, and
the React npm run build. Current implementation needs a browser walkthrough
and an actual network source fetch before being called field-validated.
