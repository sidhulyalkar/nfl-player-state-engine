# Ranking, Market & News Source Operating Policy

The Player State Engine separates four evidence families because they answer different questions:

1. **Football model** — what outcomes should this player produce?
2. **League transformation** — what are those outcomes worth under this league's scoring, roster and replacement economy?
3. **Draft market** — when is this player likely to be selected in this room/platform?
4. **External evidence** — what do independent experts, official reports and observed role signals know that our current state may be missing?

Mixing these too early creates a consensus mimic. v0.9 keeps them separate through timestamped contracts.

## Ranking source registry

The canonical registry lives in `src/player_state_engine/integrations/ranking_sources.py`.

| Source | Kind | Preferred access | Production use |
|---|---|---|---|
| FantasyPros ECR | expert | official API | calibration / disagreement |
| FantasyPros ADP | market | official API | market sensor / survival feature |
| nflverse ff rankings | expert archive | nflreadpy | historical calibration |
| Fantasy Life | expert/custom format | licensed or user export | calibration |
| ESPN rankings | expert/platform | permitted export | calibration |
| RotoWire | expert | licensed export | calibration |
| PFF | expert | licensed export | calibration |
| Rotoworld | expert/news | permitted public snapshot | calibration / evidence |
| Sleeper draft market | platform market | archived real drafts | survival model |
| ESPN draft market | platform market | archived real drafts | survival model |
| Yahoo ADP | market | permitted export | cross-market sensor |
| NFFC | sharp market | licensed export | cross-market sensor |
| FFPC | sharp market | licensed export | cross-market sensor |
| Underdog | sharp/best-ball market | licensed export | market sensor only |

## Do not scrape by default

A page being public does not make a brittle HTML scraper a good production dependency.

Preferred order:

1. maintained official API;
2. maintained public data package such as nflreadpy/nflverse;
3. platform archive already obtained through a supported integration;
4. licensed export;
5. user-provided export;
6. explicit public snapshot only when permitted and operationally justified.

Every snapshot needs a UTC capture timestamp. Historical backtests must use the latest snapshot that existed **before** the historical decision.

## FantasyPros

Configure:

```bash
export PSE_FANTASYPROS_API_KEY=...
```

Then archive a point-in-time ranking:

```bash
python scripts/fetch_fantasypros_rankings.py \
  --season 2026 \
  --position ALL \
  --scoring HALF \
  --teams 12 \
  --qb-format 2qb
```

Do not overwrite prior snapshots. Market movement and expert rank movement are information.

## Licensed/manual ranking exports

Normalize rather than custom-code every provider:

```bash
python scripts/normalize_ranking_export.py \
  --input source.csv \
  --source rotowire \
  --source-kind expert \
  --ranking-type draft \
  --scoring half_ppr \
  --teams 12 \
  --qb-format 2qb \
  --captured-at 2026-08-17T20:00:00-07:00 \
  --output data/external/rankings/rotowire/20260818T030000Z.parquet
```

The normalizer accepts common aliases such as `name`, `player`, `pos`, `team`, `ecr`, `overall_rank`, `rank_min`, `rank_max` and `rank_std`.

## Identity resolution

External rankings are matched in this order:

1. canonical player ID;
2. exact source ID only when it already matches the model namespace;
3. unique normalized name + position + team;
4. unique normalized name + position;
5. unresolved.

Match method and confidence are retained. Do not fuzzy-match an ambiguous player into a production recommendation.

## Format matching

Every ranking snapshot should include as much format metadata as possible:

- teams;
- standard / half-PPR / PPR;
- 1QB / 2QB / superflex;
- ranking type;
- capture timestamp.

The audit layer selects the nearest snapshot per source/player and assigns `format_match_confidence`. A 1QB ranking is intentionally penalized heavily when evaluating a 2QB league.

## External consensus

External expert consensus is a weighted diagnostic using:

```text
source_weight × format_match_confidence × identity_match_confidence
```

The board may expose:

- external consensus rank;
- rank standard deviation;
- min/max expert rank;
- source count;
- model-versus-external delta;
- market consensus ADP;
- cross-market dispersion.

None of these columns modifies `live_draft_score` in v0.9.

## Expert disagreement

Disagreement is evidence uncertainty, not an averaging nuisance.

A player ranked 18th by every source is different from a player with the same mean but a 7–41 range. Preserve dispersion and use it to prioritize investigation, not to automatically widen the football model without ablation evidence.

## Official and structured football evidence

Prefer structured inputs when available:

- official injury/practice status;
- nflverse injuries;
- depth charts;
- snap counts;
- participation;
- opportunity data;
- current roster transactions.

`role_state.py` converts those into typed, decayed latent-state evidence without sentiment extraction.

## Unstructured reporting

Public text is classified by evidence authority:

```text
OFFICIAL
DIRECT_OBSERVATION
REPORTED
COACH_QUOTE
PLAYER_QUOTE
ANALYSIS
SPECULATION
```

Claims map into football states such as:

```text
availability
starter_security
snap_share
route_participation
target_share
carry_share
goal_line_role
third_down_role
role_security
```

The same positive sentence therefore has different model authority depending on whether it is an official status, direct practice observation or analyst speculation.

## Beat reporters

A future source registry should record for every team reporter:

- reporter/outlet;
- team;
- canonical source URL/feed;
- source type;
- direct-practice access;
- historical reliability if measurable;
- last verified date.

Do not infer reliability from follower count. Reliability should eventually come from timestamped claim verification and ablation performance.

## Social media

Player/team social sources remain secondary. They can support travel, recovery, training and role-context hypotheses, but must earn predictive inclusion through frozen ablations. Public personas are not psychological diagnoses.

## Betting/prop markets

If licensed/authorized season-prop data is added, use it as a **model-disagreement sensor**. A large difference between our projected stat distribution and a liquid market should trigger investigation, not automatic convergence.

## Storage convention

Recommended tree:

```text
data/external/rankings/
  fantasypros/
  fantasy_life/
  espn/
  rotowire/
  pff/
  rotoworld/
  sleeper/
  yahoo/
  nffc/
  ffpc/
  underdog/

data/raw/nflverse/
  injuries.parquet
  depth_charts.parquet
  snap_counts.parquet
  ff_playerids.parquet
  ff_rankings.parquet
  ff_opportunity.parquet
```

Snapshots are append-only evidence. Derived consensus may be rebuilt; historical source snapshots should not be silently rewritten.
