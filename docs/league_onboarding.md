# League onboarding

When the fantasy league opens, copy `configs/fantasy_league_example.yaml` and enter the exact team count, roster slots, playoff weeks, risk preference, FAAB budget, tight-end premium and scoring weights.

Recommended weekly inputs:

- current roster and bench;
- all available free agents;
- league transactions and FAAB balances;
- matchup and standings context;
- keeper/dynasty rules if applicable;
- the projection and opportunity tables generated before lineup lock.

Recommended workflow:

```bash
pse fantasy-decision-board --decision draft --projections season_projections.csv
pse fantasy-decision-board --decision start_sit --projections weekly_projections.csv
pse optimize-lineup --players weekly_start_sit_scores.csv
pse rank-waivers --candidates free_agents.csv --roster my_roster.csv --faab-budget 100
```

Templates live under `examples/league/`. Platform-specific imports should normalize into these tables rather than coupling the modeling core to one fantasy provider.
