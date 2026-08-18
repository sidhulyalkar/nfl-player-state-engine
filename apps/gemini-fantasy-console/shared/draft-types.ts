export interface DraftRosterSummary {
  roster_id: string;
  team_name: string;
}

export interface DraftLeagueSummary {
  league_id: string;
  name: string;
  platform: string;
  season: number;
  imported_at?: string;
  rosters?: DraftRosterSummary[];
  external_roster_id?: string | null;
  draft_status?: string;
}

export interface DraftBoardPlayer {
  player_id: string;
  player_name: string;
  position: string;
  recent_team?: string;
  nfl_team?: string;
  live_rank: number;
  live_draft_score: number;
  draft_action: string;
  decision_specific_score?: number;
  season_points_q10?: number;
  season_points_q50?: number;
  season_points_q90?: number;
  fantasy_points_ppr_q10?: number;
  fantasy_points_ppr_q50?: number;
  fantasy_points_ppr_q90?: number;
  vorp?: number;
  floor_vorp?: number;
  upside_vorp?: number;
  replacement_rank?: number;
  league_starter_demand?: number;
  scarcity_score?: number;
  roster_need_score?: number;
  tier_cliff?: number;
  tier_cliff_percentile?: number;
  market_adp?: number | null;
  market_adp_sd?: number | null;
  survival_to_next_pick?: number;
  survival_fallback_probability?: number;
  survival_model_source?: string;
  survival_model_version?: string;
  market_urgency?: number;
  reach_rounds?: number;
  availability_probability?: number;
  opportunity_confidence?: number;
  draft_reasons?: string;
}

export interface DraftRosterPlayer extends DraftBoardPlayer {
  overall_rank?: number;
}

export interface LiveDraftPick {
  pick_no: number;
  player_id?: string;
  platform_player_id?: string;
  canonical_player_id?: string | null;
  player_name?: string;
  position?: string;
  nfl_team?: string;
  roster_id?: string | number;
  team_id?: string | number;
}

export interface SurvivalModelMetadata {
  available: boolean;
  source: string;
  version: string;
  trained_at?: string;
  rows?: number;
  drafts?: number;
  metrics?: Record<string, number | string | boolean>;
  promoted?: boolean;
  promotion_reason?: string;
}

export interface DraftBoardResponse {
  league: {
    league_id: string;
    name: string;
    platform: string;
    season: number;
    format_label: string;
    teams: number;
    roster_slots: Record<string, number>;
    scoring: string;
    median_scoring: boolean;
  };
  draft_state: {
    status: string;
    draft_slot: number;
    current_pick: number;
    next_pick?: number | null;
    total_rounds: number;
    completed_picks: number;
    recent_position_runs: Record<string, number>;
  };
  roster_id: string;
  roster: DraftRosterPlayer[];
  recent_picks: LiveDraftPick[];
  board: DraftBoardPlayer[];
  trust: {
    data_mode?: string;
    model_version?: string | null;
    projection_artifact_file_modified_at?: string | null;
    missing_inputs?: string[];
  };
  survival_model: SurvivalModelMetadata;
  refresh_warning?: string | null;
  snapshot_imported_at: string;
  snapshot_age_seconds?: number;
  projection_age_seconds?: number | null;
  stale_after_seconds?: number;
  is_stale?: boolean;
  generated_at: string;
}

export interface RosterImpact {
  player_id: string;
  player_name: string;
  position: string;
  baseline_q10: number;
  baseline_q50: number;
  baseline_q90: number;
  post_q10: number;
  post_q50: number;
  post_q90: number;
  marginal_floor: number;
  marginal_median: number;
  marginal_ceiling: number;
  simulated_delta_q10: number;
  simulated_delta_q50: number;
  simulated_delta_q90: number;
  expected_lineup_gain: number;
  probability_improves: number;
  starter_probability: number;
  projected_slot?: string | null;
  displaced_player_id?: string | null;
  displaced_player_name?: string | null;
  depth_delta: number;
  roster_fit_score: number;
  simulations: number;
  model_source: string;
}

export interface DraftCompareCandidate extends DraftBoardPlayer {
  roster_impact?: RosterImpact | null;
}

export interface DraftCompareResponse {
  league_id: string;
  roster_id: string;
  draft_state: {
    status: string;
    draft_slot: number;
    current_pick: number;
    next_pick?: number | null;
  };
  candidates: DraftCompareCandidate[];
  winners: {
    best_raw_projection?: string | null;
    best_league_value?: string | null;
    best_roster_fit?: string | null;
    best_pick_now?: string | null;
  };
  survival_model: SurvivalModelMetadata;
  refresh_warning?: string | null;
  generated_at: string;
}
