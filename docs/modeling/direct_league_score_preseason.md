# Direct league-score preseason benchmark

## Question

Can the leakage-safe preseason architecture predict the **final fantasy score under the actual league scoring contract directly**, rather than approximating fantasy-score quantiles by adding marginal stat quantiles?

This is the preferred route to exact draft-season scoring authority for fixed scoring systems. Quantiles are not additive. Historical fantasy points are.

## Population and timing

The experiment uses the same 2015–2025 Week 1 opening-roster population as the frozen direct preseason benchmark. Same-season outcomes are attached only after the season-start feature universe has been built. Missing regular-season box-score outcomes remain zero.

Training and evaluation use expanding whole-season holdouts. No target-season result enters a predictor.

## Scoring target

Each historical weekly player outcome is scored with the exact `LeagueConfig.scoring_weights` before player-season aggregation. The source contract fails closed if any nonzero scoring statistic is not represented by the public source schema.

nflverse split fields are combined before scoring:

- `fumbles_lost` = sack + rushing + receiving fumbles lost;
- `two_point_conversions` = passing + rushing + receiving two-point conversions.

Scoring is outcome-based, not position-restricted. A running back who throws a trick-play touchdown receives the passing points because that is what the league would score.

For canonical PPR, reconstructed historical scoring must exactly match nflverse `fantasy_points_ppr` on comparable rows before the benchmark proceeds.

## Frozen gate

The following gate was fixed before real benchmark results:

- primary pinball improvement >= 1%;
- held-out season win rate >= 60%;
- season-bootstrap 95% lower bound > 0;
- no position may regress more than 3%;
- rookie cohort may not regress more than 5% when sufficiently populated;
- 5,000 season-bootstrap draws, seed 42.

The gate is evaluated independently for:

- `8_team_ppr_2qb_expanded`;
- `12_team_half_ppr_median` base player scoring.

## Median scoring boundary

The half-PPR league config also declares a weekly game against the league median. That rule is **not** represented by a player-season scoring target. It remains a separate team-week policy problem and cannot become exact merely because the underlying player scoring model passes.

## Authority

All outputs are `direct_league_score_research_only`. Automatic promotion is prohibited. A passing historical result still requires a current-season materialization, immutable artifact registration, release-gate qualification, and explicit manual approval before production use.
