# Fantasy platform integration plan

## Canonical contract

Every platform must normalize into `LeagueSnapshot`:

- league identity and season;
- scoring rules and roster slots;
- managers and fantasy teams;
- owned players, starters, reserves, and injured reserve;
- free-agent pool;
- standings and points;
- waiver priority or FAAB;
- draft-pick assets for dynasty leagues;
- platform and canonical player identifiers;
- import timestamp and source URL.

## Sleeper: first-class integration

Status: implemented.

Sleeper provides a free read-only API without authentication for league, roster, user, matchup, draft, pick, player, trend, and NFL-state resources. The importer is in `integrations/sleeper.py`.

Recommended refresh:

- League settings: daily
- Rosters and users: every 15 minutes during active transaction windows
- Matchups: every few minutes on game days
- Full player map: once daily
- Trending adds/drops: hourly

The full player map is large. Cache it and avoid requesting it repeatedly.

## Yahoo: OAuth integration

Status: contract and OAuth boundary scaffolded.

Yahoo's official Fantasy Sports API supports league, team, player, roster, standings, transaction, and scoreboard resources, but access requires application approval and OAuth. The product should:

1. Redirect the user through Yahoo OAuth.
2. Store encrypted refresh tokens server-side.
3. Fetch the user's NFL game and leagues.
4. Normalize league settings, teams, rosters, free agents, and transactions.
5. Refresh tokens and snapshots through a scheduled job.

Do not ask users to paste cookies or passwords.

## Fleaflicker

Status: official API endpoint scaffolded; normalization awaits saved fixtures.

Fleaflicker publishes an HTTP API. Add fixture-driven tests for standings, rosters, players, and transactions before declaring complete support.

## ESPN

Status: manual import only until an official supported API contract is available.

The product should support:

- platform export uploaded as CSV/JSON when available;
- a browser extension that reads the user's currently displayed league page only with explicit user action;
- manual league template import;
- no credential collection or private endpoint impersonation.

Any browser extension should make collection visible, scope permissions narrowly, and normalize data locally before sending it to the Product API.

## Generic CSV

Status: implemented.

Required columns:

```text
roster_id
team_name
platform_player_id
```

Recommended columns:

```text
canonical_player_id
manager_id
manager_name
player_name
position
nfl_team
roster_slot
is_starter
is_injured_reserve
wins
losses
ties
points_for
points_against
```

CSV is the universal escape hatch and the fastest path for unsupported platforms.

## Identity resolution

Never join by player name alone when a platform identifier is available.

Preferred hierarchy:

1. GSIS ID
2. platform-maintained crosswalk
3. Sportradar or PFR identifier
4. normalized name + team + position + season, flagged as fuzzy
5. manual resolution queue

Every unresolved player must appear in a coverage report rather than silently disappearing.
