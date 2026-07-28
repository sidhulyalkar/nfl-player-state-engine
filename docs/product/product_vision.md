# Product vision: Fourth Down Lab

## Product thesis

Fantasy platforms are excellent transaction systems but fragmented decision systems. They show rosters, scores, news, and rankings, yet rarely connect the complete league economy to calibrated player distributions, roster-specific replacement value, and explicit uncertainty.

Fourth Down Lab should become a **fantasy football decision operating system** built on the Player State Engine. It should answer five questions better than a generic ranking page:

1. What is the player's current state and plausible outcome distribution?
2. What changed in role, availability, team structure, or matchup?
3. What is the player worth in this exact league?
4. Which action improves this exact roster?
5. How confident should the manager be?

## Product principles

1. **League-relative, not globally generic.** Player value depends on team count, scoring, starters, flex rules, superflex, benches, keepers, dynasty settings, and ownership.
2. **Distribution first.** Show floor, median, ceiling, scenario sensitivity, and calibration rather than one glowing point estimate.
3. **Decision-specific utilities.** Start/sit, waiver, trade, draft, and dynasty value are separate functions.
4. **Complete league picture.** Every recommendation must know who owns each player, replacement options, rival needs, standings, schedules, and transaction constraints.
5. **Evidence before prose.** Gemini explains model and tool outputs. It does not generate player values from memory.
6. **Timestamp everything.** Projections, injuries, news, league imports, and market values require point-in-time provenance.
7. **Trust is a visible feature.** Every player card should expose freshness, missing inputs, interval calibration, model version, and reason codes.

## Primary users

### The serious home-league manager

Wants an advantage without maintaining spreadsheets, downloading data, or interpreting model diagnostics.

### The dynasty manager

Needs multi-year priors, rookie ranges, draft-pick assets, age curves, role access, and contender-versus-rebuilder context.

### The analyst and model builder

Needs calibration, feature attribution, backtests, archived predictions, counterfactual scenarios, and exportable tables.

## Core jobs to be done

- Import a league in under two minutes.
- Understand the manager's roster strengths, fragilities, and leverage points.
- Optimize a lineup for matchup context and risk appetite.
- Identify free agents who can capture newly available opportunity.
- Generate trades that have a credible benefit for both managers.
- Compare players through the full opportunity ladder.
- Explain why a recommendation changed since the previous refresh.
- Track whether the model's recommendations actually improve decisions.

## Product surfaces

### Command Center

- Current record and playoff probability
- Roster floor, median, ceiling, and risk concentration
- Starting-lineup alerts
- Injury and depth-chart changes
- Highest-leverage waiver and trade opportunities
- Model freshness and data-quality warnings

### League Picture

- Power rankings with calibrated uncertainty
- Positional strength heatmap
- Ownership matrix for all relevant NFL players
- Contender, bubble, and rebuild classifications
- Schedule strength and playoff-path simulations
- Manager tendencies where transaction history is available

### Player Lab

- Weekly and season distributions
- Active → snaps → routes/carries → targets → conversion funnel
- Team context and opponent context
- Historical role trajectory
- Scenario controls for teammate availability, game total, pace, and workload
- League-relative replacement and scarcity
- Comparable players and rookie analogs
- Evidence timeline with source timestamps

### Trade Lab

- Drag-and-drop multi-team trade builder
- Before/after legal lineup optimization
- Floor, median, ceiling, depth, positional need, and playoff effects
- Fairness and mutual-benefit estimates
- Dynasty pick and age-curve support
- Suggested trades based on complementary needs
- Counteroffers that improve acceptance probability

### Opportunity Wire

- Free agents and lightly rostered players
- Vacated targets/carries and depth promotion
- Role-growth and breakout probability
- FAAB recommendation ranges
- Expected duration of the opportunity
- Add/drop regret tracking

### Lineup Lab

- Legal lineup optimization
- Floor-versus-ceiling control
- Correlated game simulation
- Matchup win probability
- Late-swap and inactive contingencies
- Explanation of every starter/bench difference

### NFL State

- Team records, standings, and point differential
- Dynamic offense and defense strength states
- Pace, neutral pass rate, personnel, and formation fingerprints
- Coaching and quarterback changes
- Injury density and offensive-line continuity
- Game environment distributions

### Model Lab

- Out-of-sample metrics by season, target, and position
- Calibration and interval coverage
- Champion/challenger history
- Data freshness and source coverage
- Feature-family ablations
- Recommendation outcome tracking

## Monetizable product layers

- Free: one league, basic imports, weekly projections, player comparison.
- Plus: unlimited leagues, lineup and waiver tools, historical trends, Gemini explanations.
- Pro: trade suggestions, dynasty tools, scenario simulation, deeper model diagnostics, exports.
- Analyst/API: bulk data, model endpoints, archived predictions, custom scoring, research tools.

Monetization should follow demonstrated decision value. Do not hide calibration failures behind a paywall-shaped curtain.
