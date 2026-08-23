export type NavPage =
  | 'overview'
  | 'league'
  | 'players'
  | 'intelligence'
  | 'trade'
  | 'waivers'
  | 'lineup'
  | 'nfl'
  | 'model';

export type DataMode = 'synthetic' | 'historical' | 'live' | 'unverified';
export type DecisionType = 'start_sit' | 'waiver' | 'trade' | 'draft' | 'stash' | 'dynasty';

export interface LeagueSummary {
  league_id: string;
  name: string;
  platform: string;
  season: number;
}

export interface PlayerRow {
  player_id: string;
  player_name: string;
  position: string;
  recent_team?: string;
  owner_team_name?: string | null;
  owner_roster_id?: string | null;
  is_free_agent?: boolean;
  decision_type?: DecisionType | string;
  decision_specific_score?: number;
  decision_percentile?: number;
  overall_rank?: number;
  position_rank?: number;
  fantasy_points_ppr_q10?: number;
  fantasy_points_ppr_q50?: number;
  fantasy_points_ppr_q90?: number;
  season_points_q10?: number;
  season_points_q50?: number;
  season_points_q90?: number;
  replacement_points?: number;
  roster_replacement_value?: number;
  vorp?: number;
  floor_vorp?: number;
  upside_vorp?: number;
  availability_probability?: number;
  opportunity_confidence?: number;
  breakout_probability?: number;
  role_growth_score?: number;
  scheme_fit_score?: number;
  schedule_score?: number;
  playoff_schedule_score?: number;
  prospect_prior_score?: number;
  age?: number;
  market_adp?: number;
  market_value_gap?: number;
  uncertainty?: number;
  waiver_upgrade?: number;
  recommended_faab?: number;
  recommended_faab_pct?: number;
  faab_recommendation?: number;
  lineup_slot?: string;
  slot?: string;
  assigned_slot?: string;
  lineup_score?: number;
  current_lineup_slot?: string | null;
  is_current_starter?: boolean;
  replaces_player_name?: string | null;
  lineup_delta?: number;
  decision_reasons?: string;
  prediction_timestamp?: string;
  feature_cutoff?: string;
  source_cutoff?: string;
  model_version?: string;
  projection_artifact_file_modified_at?: string;
  data_mode?: string;
  missing_inputs?: string[];
}

export interface PowerRanking {
  roster_id: string;
  team_name: string;
  record: string;
  power_score: number;
  roster_value: number;
  floor_value: number;
  ceiling_value: number;
  risk_score: number;
}

export interface TradeSide {
  roster_id: string;
  value_delta: number;
  starter_delta: number;
  floor_delta?: number;
  ceiling_delta?: number;
  depth_delta?: number;
  reasons: string[];
}

export interface TradeSuggestion {
  explanation: string;
  analysis: {
    fairness_score: number;
    mutual_benefit_score: number;
    confidence: number;
    verdict: string;
    side_a: TradeSide;
    side_b: TradeSide;
  };
  trade: {
    side_a_player_ids?: string[];
    side_b_player_ids?: string[];
    [key: string]: unknown;
  } | unknown;
}

export interface NFLTeamState {
  team: string;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  point_differential: number;
  win_percentage: number;
  streak?: string | null;
}

export interface NFLStateSnapshot {
  data_mode?: string;
  season: number;
  week?: number | null;
  teams: NFLTeamState[];
}

export interface PositionNeed {
  position: string;
  position_strength?: number;
  league_reference?: number;
  need_score: number;
  need_percentile?: number;
  strength_rank?: number;
  need_rank?: number;
}

export interface RosterNeeds {
  roster_id: string;
  team_name?: string;
  positions: PositionNeed[];
}

export interface LeagueNeedsResponse {
  data_mode?: string;
  league_id?: string;
  model_version?: string;
  projection_artifact_file_modified_at?: string;
  identity_coverage?: {
    total_players: number;
    resolved_players: number;
    unresolved_players: number;
    coverage_rate: number;
    unresolved_player_ids: string[];
  };
  missing_inputs?: string[];
  needs: Array<PositionNeed & { roster_id: string; team_name?: string }>;
}

export interface ResearchMetric {
  name?: string;
  metric?: string;
  value: number;
  baseline_value?: number;
  delta?: number;
  unit?: string;
  note?: string;
}

export interface ResearchExperiment {
  experiment_id: string;
  name?: string;
  status: 'promote' | 'reject' | 'revise' | 'blocked' | string;
  hypothesis?: string;
  summary?: string;
  primary_metric?: string;
  metric_value?: number;
  baseline_value?: number;
  coverage?: number;
  source_coverage?: number;
  negative_controls_passed?: boolean | null;
}

export interface ResearchSummary {
  data_mode?: string;
  artifact_file_modified_at?: string;
  missing_inputs?: string[];
  artifacts?: Record<string, ArtifactMetadata>;
  benchmark: Array<Record<string, string | number | boolean | null>>;
  conformal: Array<Record<string, string | number | boolean | null>>;
  frozen_opportunity: Array<Record<string, string | number | boolean | null>>;
  historical_sources: Array<Record<string, string | number | boolean | null>>;
  historical_source_coverage: Array<Record<string, string | number | boolean | null>>;
}

export interface ResearchPrediction {
  player_id: string;
  player_name: string;
  position: string;
  team?: string;
  recent_team?: string;
  season: number;
  week: number;
  target?: string;
  q10?: number;
  q50?: number;
  q90?: number;
  actual?: number | null;
  overall_rank?: number;
  position_rank?: number;
  method?: string;
  model_version?: string;
  prediction_timestamp?: string;
  feature_cutoff?: string;
}

export interface ResearchPredictionsResponse {
  data_mode?: string;
  artifact?: ArtifactMetadata;
  filters?: Record<string, string | number | null>;
  total_matches?: number;
  returned?: number;
  missing_inputs?: string[];
  predictions: ResearchPrediction[];
}

export interface ArtifactMetadata {
  available: boolean;
  path?: string;
  file_modified_at?: string;
  row_count?: number;
  cutoff?: string;
  excluded_columns?: string | string[];
  source?: string;
  target?: string;
}

export interface TeamContextRow {
  team?: string;
  recent_team?: string;
  season?: number;
  week?: number;
  pace?: number;
  plays_per_game?: number;
  neutral_pass_rate?: number;
  target_concentration?: number;
  rush_concentration?: number;
  source?: string;
  feature_cutoff?: string;
  [key: string]: string | number | undefined;
}

export interface TeamContextResponse {
  data_mode?: string;
  artifact?: ArtifactMetadata;
  filters?: Record<string, string | number | null>;
  total_matches?: number;
  returned?: number;
  missing_inputs?: string[];
  teams: TeamContextRow[];
}

export interface DataProvenance {
  mode: DataMode;
  label: string;
  modelVersion?: string;
  predictionTimestamp?: string;
  artifactModifiedAt?: string;
  featureCutoff?: string;
  sourceCoverage?: number;
  unresolvedPlayerIds?: number;
  missingInputs?: string[];
}

export interface PlayerProjectionShape {
  q10: number | null;
  q50: number | null;
  q90: number | null;
  interval_width: number | null;
  downside_from_median: number | null;
  upside_from_median: number | null;
  relative_interval_width: number | null;
}

export interface PlayerDecisionMatrixRow {
  decision: DecisionType;
  score: number | null;
  percentile: number | null;
  overall_rank: number | null;
  position_rank: number | null;
  reasons: string | null;
  vorp: number | null;
  floor_vorp: number | null;
  upside_vorp: number | null;
  replacement_points: number | null;
  scarcity_score: number | null;
  market_adp: number | null;
  market_value_gap: number | null;
}

export interface PlayerSignal {
  key: string;
  label: string;
  value: number;
  status: 'positive' | 'neutral' | 'watch' | 'risk' | string;
}

export interface PlayerIntelligenceResponse {
  player: {
    player_id: string;
    player_name: string;
    position: string | null;
    team: string | null;
    age: number | null;
    owner_roster_id: string | null;
    owner_team_name: string | null;
    is_free_agent: boolean;
  };
  projection: PlayerProjectionShape;
  replacement_margins: { q10: number | null; q50: number | null; q90: number | null };
  decision_matrix: PlayerDecisionMatrixRow[];
  signals: PlayerSignal[];
  raw_model_fields: Record<string, unknown>;
  league: {
    teams: number;
    scoring: string;
    roster_slots: Record<string, number>;
    flex_eligibility: Record<string, string[]>;
    risk_preference: number;
    median_scoring: boolean;
    median_game_weight: number;
    tight_end_premium: number;
    faab_budget: number | null;
  };
  trust: Record<string, unknown>;
  authority: {
    production_projection_authoritative: boolean;
    decision_board_authoritative: boolean;
    player_state_graph_authority: string;
    forecast_trust_is_guardrail: boolean;
    note: string;
  };
}

export interface ShadowProjection {
  q10: number | null;
  q50: number | null;
  q90: number | null;
}

export interface OpportunityFamilyAudit {
  raw_modeled_total: number;
  normalization_applied: boolean;
  normalization_scale: number;
  coherent_modeled_total: number;
  residual_unmodeled_share: number;
  players: Array<{
    player_id: string;
    position?: string;
    raw_share: number;
    coherent_share: number;
    is_selected_player: boolean;
  }>;
}

export interface PlayerShadowResponse {
  data_mode: string;
  player_id: string;
  graph_health: {
    root: string;
    available: boolean;
    artifacts: Record<string, ArtifactMetadata>;
  };
  comparison: {
    available: boolean;
    reason?: string;
    comparable_horizon?: boolean;
    decision_comparable?: boolean;
    production?: ShadowProjection;
    challenger?: ShadowProjection;
    disagreement?: {
      median_delta: number | null;
      interval_width_delta: number | null;
      interval_overlap_ratio: number | null;
      direction: string;
    };
    graph_context?: Record<string, unknown>;
    scoring_contract?: {
      comparable: boolean;
      status: string;
      note: string;
      graph_contract?: Record<string, unknown>;
    };
    authority?: {
      production: string;
      challenger: string;
      may_change_decision: boolean;
    };
  };
  opportunity: {
    available: boolean;
    reason?: string;
    authority?: string;
    team?: string | null;
    season?: number | null;
    week?: number | null;
    target_share?: OpportunityFamilyAudit | null;
    carry_share?: OpportunityFamilyAudit | null;
    note?: string;
  };
}

export interface ScenarioDistribution {
  baseline: ShadowProjection;
  scenario: ShadowProjection;
  median_delta: number;
  center_factor: number;
  uncertainty_factor: number;
  baseline_availability: number;
  scenario_availability: number;
}

export interface PlayerScenarioResponse {
  semantics: string;
  engine: string;
  controls: {
    role_multiplier: number;
    team_volume_multiplier: number;
    availability_probability: number | null;
  };
  production: ScenarioDistribution | null;
  challenger: ScenarioDistribution | null;
  scoring_contract: {
    comparable: boolean;
    status: string;
    note: string;
  };
  authority: {
    may_override_production: boolean;
    note: string;
  };
}

export interface PortfolioExposurePlayer {
  player_key: string;
  canonical_player_id?: string | null;
  player_name: string;
  position?: string | null;
  nfl_team?: string | null;
  league_count: number;
  exposure_rate: number | null;
  starter_leagues: number;
  starter_exposure_rate: number | null;
  identity_quality: string;
  leagues: Array<{
    league_id: string;
    league_name: string;
    team_name: string;
    is_starter: boolean;
    roster_slot?: string | null;
  }>;
  projection?: Record<string, unknown>;
}

export interface PortfolioExposureResponse {
  data_mode: string;
  authority: {
    identity_aggregation: string;
    unresolved_leagues_are_excluded: boolean;
    projection_values: string;
    note: string;
  };
  summary: {
    stored_leagues: number;
    resolved_user_rosters: number;
    unresolved_user_rosters: number;
    unique_player_keys: number;
    total_roster_slots: number;
    maximum_single_player_exposure: number;
    canonical_identity_rows: number;
    platform_scoped_identity_rows: number;
  };
  leagues: Array<Record<string, string | number | boolean | null>>;
  unresolved_leagues: Array<Record<string, string>>;
  players: PortfolioExposurePlayer[];
  team_concentration: Array<{ nfl_team: string; roster_slots: number; slots_per_resolved_league: number }>;
  position_concentration: Array<{ position: string; roster_slots: number; slots_per_resolved_league: number }>;
}

export interface ShadowEvaluationResponse {
  data_mode: string;
  authority: string;
  reason?: string;
  paired_rows?: number;
  seasons?: number;
  metrics?: {
    champion_mean_pinball: number;
    challenger_mean_pinball: number;
    pinball_effect_champion_minus_challenger: number;
    champion_q50_mae: number;
    challenger_q50_mae: number;
    champion_80_coverage: number;
    challenger_80_coverage: number;
    champion_mean_width: number;
    challenger_mean_width: number;
    overlap_rate: number;
  };
  bootstrap?: Record<string, number> | null;
  promotion_record?: Record<string, unknown>;
  promotion_status?: string;
  blockers?: string[];
  note?: string;
}

export interface ModelDiagnosticRow {
  scope: string;
  rows: number;
  position?: string;
  season?: number;
  empirical_80_coverage?: number;
  coverage_gap?: number;
  calibration_status?: string;
  q50_mae?: number;
  median_bias?: number;
  mean_interval_width?: number;
  lower_miss_rate?: number;
  upper_miss_rate?: number;
  pinball_q10?: number;
  pinball_q50?: number;
  pinball_q90?: number;
  mean_pinball?: number;
  mean_interval_score_80?: number;
  crossed_quantile_rate_before_repair?: number;
}

export interface ModelDiagnosticsResponse {
  data_mode: string;
  authority: string;
  target_coverage: number;
  method: string;
  target: string;
  minimum_rows: number;
  artifact: ArtifactMetadata;
  overall: ModelDiagnosticRow;
  by_position: ModelDiagnosticRow[];
  by_season: ModelDiagnosticRow[];
  by_position_season: ModelDiagnosticRow[];
}

export interface ModelObservatoryResponse {
  data_mode: string;
  authority: {
    production_champion: string;
    player_state_graph: string;
    diagnostics: string;
    promotion_is_automatic: boolean;
  };
  artifact_health: {
    available: number;
    total: number;
    missing: string[];
    latest_file_modified_at?: string | null;
  };
  player_state_graph?: {
    health: {
      root: string;
      available: boolean;
      artifacts: Record<string, ArtifactMetadata>;
    };
    manifest: Record<string, unknown> | null;
    shadow_evaluation: ShadowEvaluationResponse;
  };
  diagnostics: ModelDiagnosticsResponse;
  benchmark: Array<Record<string, string | number | boolean | null>>;
  conformal: Array<Record<string, string | number | boolean | null>>;
  frozen_opportunity: Array<Record<string, string | number | boolean | null>>;
  historical_sources: Array<Record<string, string | number | boolean | null>>;
  historical_source_coverage: Array<Record<string, string | number | boolean | null>>;
}
