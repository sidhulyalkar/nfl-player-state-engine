# Live Draft Room — 2026 Fantasy Season

The draft layer is no longer a universal ranking table. It is a live decision engine that recalculates player value from the exact league economy and the current state of the room.

## The three target league shapes

Two reusable profiles ship with the repository:

- `configs/fantasy/12_team_half_ppr_median.yaml`
  - 12 teams
  - half PPR
  - weekly-median scoring flag enabled
  - conventional 1QB baseline roster, intended to be replaced automatically by live platform settings when available
- `configs/fantasy/8_team_ppr_2qb_expanded.yaml`
  - 8 teams
  - full PPR
  - 2 QB
  - 3 RB
  - 3 WR
  - 3 FLEX
  - 1 TE
  - DST and K

The two 8-team leagues can share the same valuation profile while remaining separate live league connections.

## Why rankings change by league

The engine now estimates replacement demand from the actual starter slots. Fixed starters are allocated first, then every flexible starter seat is assigned to the eligible position with the strongest next projected player. This eliminates the old hard-coded FLEX split.

That matters enormously in the expanded 8-team format. Sixteen QBs are mandatory starters before bench depth, while 24 RB, 24 WR and another 24 flexible RB/WR/TE seats are consumed. An 8-team league is therefore not automatically a shallow league. This format creates a very unusual combination of shallow manager count and deep weekly starter demand.

The live board combines:

1. model value over league-specific replacement
2. floor and ceiling distributions
3. roster construction need
4. positional tier cliffs
5. probability the player survives to your next snake pick
6. market ADP without treating ADP as fantasy points
7. opportunity confidence and availability
8. weekly-floor preference for median-scoring formats

## Market timing

ADP is a timing signal, not a football-value unit. v0.7 removes the old raw subtraction of `market_cost` from draft utility.

When `market_adp` is present, the engine estimates:

- `survival_to_next_pick`
- `market_urgency`
- `reach_rounds`

A player can therefore be the best football value but still receive a `WAIT` label if the market strongly suggests he will survive the turn. Conversely, a tier-closing player unlikely to make it back can become `DRAFT NOW`.

## Live Sleeper sync

Sleeper is the preferred first platform because its official read-only API exposes users, leagues, rosters, settings, drafts, draft picks, matchups and NFL state without an API token.

A Sleeper connection can specify either a league ID or a username. Username mode discovers all NFL leagues for the configured season. The large player map is cached once per importer process so syncing several leagues does not repeatedly download it.

During an active draft, snapshots include:

- the active draft object
- all completed picks
- current pick inferred from pick count
- the user's roster ID when a Sleeper user ID is known
- every league roster and manager
- current league settings and scoring

## ESPN sync

ESPN support is intentionally isolated behind an optional adapter:

```bash
pip install -e ".[espn]"
```

The adapter uses `espn-api>=0.46.0`. Public leagues can work from league ID and season. Private leagues require ESPN session cookies. Store them only in environment variables:

```bash
export PSE_ESPN_S2='...'
export PSE_ESPN_SWID='{...}'
```

Never commit those values. Snapshots record only whether credentials were present, never the credentials themselves.

ESPN is treated as a best-effort source boundary because its fantasy interface is not the same stable public contract as Sleeper. If ESPN changes a secondary endpoint such as free agents, the core league snapshot can still load instead of failing the entire product.

## Configure all leagues

Copy:

```bash
cp configs/fantasy/leagues.example.yaml configs/fantasy/leagues.yaml
```

Then fill in the platform IDs and usernames.

Sync every league:

```bash
python scripts/sync_fantasy_leagues.py --config configs/fantasy/leagues.yaml
```

Snapshots are written under:

```text
data/product/live_leagues/
```

## Generate the board during a draft

Your projection table must contain at least:

```text
player_id
player_name
position
season_points_q10
season_points_q50
season_points_q90
```

Recommended live-market columns:

```text
market_adp
market_adp_sd
```

Then run:

```bash
python scripts/live_draft_board.py \
  --snapshot data/product/live_leagues/league_8_ppr_a.json \
  --projections artifacts/predictions/2026_draft_projections.parquet \
  --profile configs/fantasy/8_team_ppr_2qb_expanded.yaml \
  --draft-slot 5
```

After every platform refresh, rerun the board. Completed picks disappear, roster needs change, positional cliffs move, and the next-pick survival calculation updates.

## Key output columns

- `live_rank`: recommendation order right now
- `live_draft_score`: 0–100 room-aware score
- `draft_action`: `DRAFT NOW`, `TARGET`, `WAIT`, or `CONSIDER`
- `vorp`: median value over league-specific replacement
- `replacement_rank`: player depth defining replacement for this format
- `league_starter_demand`: estimated league-wide starters at the position
- `roster_need_score`: your current construction pressure
- `tier_cliff_percentile`: severity of the drop after the player
- `survival_to_next_pick`: probability estimate that the player reaches your next selection
- `reach_rounds`: how far ahead of market the current pick would be
- `draft_reasons`: concise explanation of the recommendation

## Next data integrations

The architecture is intentionally platform-neutral. Yahoo, Fleaflicker or another service can implement `LeagueImporter` and emit the same `LeagueSnapshot`. The draft engine should never need platform-specific logic.

The next research layer should add empirical platform-specific draft-position distributions, consensus ADP/ECR ingestion, 2026 projection refresh jobs, and full weekly team simulation for the median-scoring league. The current median adjustment is intentionally conservative until that simulation is available.
