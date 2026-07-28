# Intelligence activation plan

## Principle

Intelligence should explain changes in **participation and opportunity** before it attempts to move yardage or fantasy-point predictions directly.

A news feature that says “expected to be limited” belongs first in a snap-share distribution. Letting it directly subtract 4.7 fantasy points skips the causal machinery and invites narrative overfitting.

## Stage 0: frozen numerical benchmark

Status: complete.

- 2020 warm-up, 2021–2025 out of sample.
- Quantile engine compared with rolling and position-prior baselines.
- Pooled engine won six of seven targets.
- Carries failure diagnosed and corrected with position-specific heads.

## Stage 1: objective participation intelligence

Activate one family at a time:

- official game designation;
- practice participation trend;
- inactive list;
- transactions and injured reserve;
- depth-chart position;
- recent snap share and route participation;
- quarterback and offensive-line availability.

Primary heads:

- probability active;
- expected snaps;
- routes;
- team attempts/plays;
- carries;
- targets.

Acceptance criterion: improve held-out pinball loss and/or calibration in at least three seasons without material position regression.

## Stage 2: structured news role evidence

Extract only timestamped football claims such as:

- expected workload restriction;
- starter/backup role;
- committee change;
- target or route role;
- coach-announced usage;
- weather or travel disruption.

Keep source reliability, quote/evidence span, published time, and uncertainty. Compare against Stage 1 to determine whether news adds information beyond official reports.

## Stage 3: public player-context features

Candidate features:

- recent training discussion;
- recovery discussion;
- matchup-specific preparation;
- explicit role expectations;
- team and leadership language;
- media/commercial content share;
- posting volume and source diversity.

Use these only as low-weight residual modifiers or uncertainty signals. Do not infer private psychology, diagnoses, sensitive traits, or “motivation” as a ground-truth label.

Required ablations:

1. numerical baseline;
2. baseline + official availability;
3. baseline + objective opportunity;
4. baseline + news;
5. baseline + public context;
6. baseline + all approved intelligence;
7. shuffled-player and shifted-time negative controls.

The shuffled-player control asks whether generic weekly chatter improves everyone. The shifted-time control asks whether accidental future leakage is carrying the ball.

## Stage 4: sequence and matchup intelligence

After opportunity heads are stable:

- play-by-play sequence encoder;
- personnel and formation embeddings;
- coverage and pressure tendencies;
- line matchup features;
- coaching/play-caller state;
- tracking-derived route and defender interactions.

The public-context layer should remain optional even here. If it adds no stable value, retire it cheerfully rather than building a shrine around an interesting idea.

## v0.4 note

Before adding deeper models, inspect `docs/calibration_real_2021_2025.md`, `docs/opportunity_engine.md`, and `docs/intelligence_experiments.md`. Opportunity and intelligence modules are implemented but disabled until their real multi-season ablations pass. Continual challengers embed earlier-residual conformal calibrators; do not fit calibration on the evaluation season.
