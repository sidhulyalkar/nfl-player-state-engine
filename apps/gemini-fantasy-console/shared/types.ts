export type NavPage =
  | 'overview'
  | 'league'
  | 'players'
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
