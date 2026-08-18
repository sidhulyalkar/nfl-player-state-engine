# v0.11 Game Intelligence: Frozen Replay and Opportunity Allocation

v0.11 changes the research question from **"can we build a richer simulator?"** to **"which layer of the simulator earns additional complexity under frozen point-in-time replay?"**

The release therefore adds stronger evaluation before deeper modeling.

## Canonical causal decomposition

```text
pregame evidence
    -> team environment
    -> play-call probability
    -> realized/simulated play family
    -> player opportunity allocation
    -> play outcome / efficiency
    -> correlated player stat draws
    -> exact league scoring
    -> fantasy decision utility
```

Every layer must be measurable independently. A downstream fantasy miss must not automatically be blamed on the play-call model, and an opportunity model must not receive credit for a team-volume improvement it did not produce.

## 1. Expanding weekly frozen replay

The v0.10 replay could train once before a test window and reuse that model through the window. That is leakage-safe, but it is not the intended continual-learning protocol.

v0.11 makes the canonical benchmark **expanding weekly**:

```text
predict Week 1 using data strictly before Week 1
predict Week 2 using data strictly before Week 2
predict Week 3 using data strictly before Week 3
...
```

A Week 8 replay may learn from Weeks 1-7. It may never learn from Week 8 itself.

The runner is:

```bash
python scripts/run_v011_game_benchmark.py \
  --pbp data/raw/game_intelligence/v011/play_by_play.parquet \
  --schedules data/raw/game_intelligence/v011/schedules.parquet \
  --players data/raw/game_intelligence/v011/players.parquet \
  --player-actuals data/raw/game_intelligence/v011/player_stats.parquet \
  --test-season 2023 \
  --test-season 2024 \
  --test-season 2025
```

The GitHub Actions workflow `.github/workflows/v011_historical_game_benchmark.yml` provides the same protocol as a reproducible manual benchmark.

## 2. Three evidence levels

v0.11 deliberately labels three different kinds of evidence.

### A. Full pregame game replay

Everything available to the simulator is frozen before kickoff. This is the only evidence class that can support production promotion.

Metrics include:

- play-call log loss and Brier score;
- team plays MAE;
- team pass-rate MAE;
- team points MAE;
- player opportunity MAE;
- fantasy quantile pinball loss;
- q10-q90 interval coverage.

### B. Oracle-state opportunity diagnostics

The state-conditioned opportunity head is first evaluated while conditioning on the **realized sequence of play states and play families**.

That answers a narrower question:

> If team volume and run/pass choice were already correct, does situational history allocate the carry or target better than static recent share?

This is intentionally not presented as a deployable pregame projection. It isolates allocation quality before coupling the allocator to simulated states.

### C. Historical direct/generative blending

Archived direct-model and game-simulator quantiles can be blended only after they have both been generated point-in-time.

The blend learns weights using earlier archived predictions only. The current week is never part of the calibration set.

## 3. State-conditioned opportunity allocator

`StateConditionedOpportunityModel` keeps player identity explicit and estimates a hierarchical distribution over the player receiving the next carry or target.

The base prior is the team's recency-weighted player allocation. Situational distributions are independently estimated for:

- red zone;
- third down;
- early downs;
- late game;
- leading / neutral / trailing score state;
- distance bucket;
- field zone.

Each situational distribution is shrunk toward the base share:

```text
alpha = context evidence / (context evidence + prior strength)
```

The final distribution is a convex evidence-weighted blend rather than an unregularized context table. Sparse states therefore cannot zero out established players or dominate the prior after one unusual game.

### Current promotion boundary

The allocator does **not** yet drive Monte Carlo player selection.

Required sequence:

1. win the oracle-state allocation benchmark;
2. inspect carry and target results separately;
3. inspect temporal and team stability;
4. integrate into simulated states behind a challenger flag;
5. rerun full pregame replay;
6. promote only if downstream fantasy calibration also improves.

## 4. Direct + generative quantile blend

The direct numerical model and the game simulator make different errors.

v0.11 adds `QuantileBlendCalibrator` to test whether those errors are complementary.

For each quantile:

```text
Q_blend = w * Q_direct + (1 - w) * Q_generative
```

The calibrator:

- learns `w` from historical prediction rows only;
- can learn position-specific weights when sample size is sufficient;
- falls back to a global weight otherwise;
- enforces q10 <= q50 <= q90 after blending;
- reports whether the blend beats direct, generative, and the better component on each weekly fold.

The blend remains research-only. It cannot replace production projections merely because a fitted weight exists.

## 5. v0.11 promotion gate

The gate is intentionally stricter than a single aggregate score.

Default requirements include:

- at least three held-out seasons;
- at least 200 replayed games;
- play-call challenger beats the transparent profile baseline;
- no material regression in team play volume, pass rate, scoring, or player opportunity;
- core metrics win a majority of weekly folds;
- state-conditioned allocation log loss beats static recent share;
- downstream fantasy pinball loss does not regress;
- q10-q90 coverage remains in an acceptable research band;
- manual champion review remains required.

Missing downstream evidence is a failed gate, not a neutral result.

## 6. What should be built next only after benchmark evidence

The next model family should be selected by the replay decomposition.

### If team plays are the bottleneck

Build a pace / drive-volume model using:

- neutral seconds per play;
- no-huddle rate;
- opponent pace interaction;
- first-down conversion rate;
- expected drive starts;
- fourth-down aggressiveness;
- score-state pace response.

### If player allocation is the bottleneck

Integrate the v0.11 opportunity allocator into simulated states, then add richer evidence in this order:

1. active-roster / depth-chart eligibility;
2. routes and pass-play participation;
3. alignment and personnel;
4. third-down / two-minute / goal-line packages;
5. first-read or route-concept proxies where legitimately available.

### If play outcomes are the bottleneck

Replace broad empirical strata with conditional outcome heads for:

- pressure / sack;
- completion;
- air yards;
- yards after catch;
- rushing yards;
- explosive-play probability;
- turnover probability;
- touchdown conversion.

Do not combine these into one black-box outcome model until individual calibration is understood.

### If game-script transitions are the bottleneck

Add a latent drive strategy state such as:

```text
SCRIPTED
NORMAL
HURRY_UP
CLOCK_CONTROL
COMEBACK
RED_ZONE_PACKAGE
```

The state should persist across several plays and transition using observed evidence. This is a cleaner next sequence model than immediately adding a transformer over raw plays.

## 7. High-value evidence families after v0.11

Candidate families remain experiments, not trusted inputs by default:

- offensive-line starter continuity and pressure responsibility;
- defensive front / coverage-response proxies;
- personnel and formation transitions;
- motion / play-action / RPO / screen usage;
- route participation and alignment;
- drive opening scripts and halftime adaptation;
- weather trajectory rather than kickoff-only weather;
- rest, travel, surface, roof, and time-zone effects;
- official crews and penalty environment;
- market disagreement as an external diagnostic sensor;
- verified coaching/play-caller changes and matchup history.

Every family needs timestamp provenance, a frozen ablation, and a negative control.

## 8. Continual-learning target

During the season the system should maintain a weekly error ledger:

```text
prediction
    -> actual game
    -> layer attribution
       - volume
       - play call
       - allocation
       - efficiency
       - scoring / uncertainty
    -> challenger experiment
    -> frozen replay
    -> promotion gate
```

The desired outcome is not uncontrolled online learning. It is a system that becomes more informed every week while preserving reproducibility and a manually governed production champion.
