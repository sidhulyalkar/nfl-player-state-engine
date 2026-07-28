# Roadmap and Gates

## Gate 0: Reproducible baseline

- [x] Synthetic offline smoke test
- [x] Leakage-safe weekly features
- [x] Target-aware hybrid quantile models
- [x] Temporal holdout
- [x] Correlated simulation scaffold
- [x] Paper prop scorer

## Gate 1: Historical NFL benchmark

- [x] Download and checksum 2020–2025 nflverse data
- [x] Multi-season benchmark command and reproducibility script
- [x] Rolling-stat quantile baseline
- [x] Position-prior quantile baseline
- [x] Position and season metrics
- [x] Quantile calibration and interval sharpness
- [x] Core target sweep
- [x] Carries failure analysis
- [x] Position-specific carries correction
- [x] Source and benchmark manifests
- [ ] Expand the error taxonomy with manually reviewed player-week examples

Exit condition: achieved for numerical baseline development. The pooled model won six of seven targets, and the corrected hybrid architecture addresses the carries failure.

## Gate 2: Calibration and opportunity engine

- [ ] Target-and-position conformal calibration
- [ ] Snap-share model
- [ ] Route-participation model
- [ ] Team pass/rush volume model
- [ ] Target-share and carry-share models
- [x] Availability schema and point-in-time join scaffold
- [ ] Depth-chart and roster transaction reconciliation
- [ ] Rookie, trade, and return-from-injury priors

Exit condition: decomposed models improve opportunity calibration across at least three held-out seasons without material subgroup regression.

## Gate 3: Availability and role intelligence

- [ ] Official practice and game-status ingestion
- [ ] Inactive and transaction ingestion
- [ ] Depth-chart change detection
- [ ] Quarterback and offensive-line continuity
- [ ] Structured licensed-news role extraction
- [ ] Human review queue and source reliability calibration

Exit condition: objective intelligence improves active probability, participation, and workload distributions beyond the numerical engine.

## Gate 4: Public context

- [x] Public-document and evidence schemas
- [x] Official API connector scaffolds
- [x] RSS and static public-page collectors
- [x] Rendered public-page collector with access-boundary guards
- [x] Conservative persona feature extractor
- [x] Point-in-time join
- [x] Matchup-scenario hypothesis scaffold
- [ ] Frozen-fold public-context ablation
- [ ] Shuffled-player negative control
- [ ] Shifted-time leakage control
- [ ] Source and platform drift monitoring

Exit condition: public-context features improve multiple held-out seasons beyond official availability and objective opportunity features. Otherwise they are retired.

## Gate 5: Game simulator

- [ ] Team pace and pass-rate-over-expected states
- [ ] Drive or play-level state transitions
- [ ] Learned residual correlations
- [ ] In-game injuries and substitutions
- [ ] Counterfactual game scripts

## Gate 6: Football representation model

- [ ] Self-supervised play-sequence pretraining
- [ ] Player/team embeddings
- [ ] Formation and matchup graph
- [ ] Big Data Bowl tracking experiments
- [ ] Multi-task football-state heads

Exit condition: learned states transfer across seasons, teams, and downstream tasks better than handcrafted states.
