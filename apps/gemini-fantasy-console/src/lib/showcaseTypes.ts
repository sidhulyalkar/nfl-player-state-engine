export type ShowcaseWinner = 'model' | 'expert' | 'tie' | 'unavailable';

export interface ShowcaseScopeMetrics {
  rows: number;
  position: string;
  model_mae?: number | null;
  model_rmse?: number | null;
  model_bias?: number | null;
  model_spearman?: number | null;
  model_rank_mae?: number | null;
  expert_mae?: number | null;
  expert_rmse?: number | null;
  expert_bias?: number | null;
  expert_spearman?: number | null;
  expert_rank_mae?: number | null;
  model_mae_advantage?: number | null;
  top_n?: number;
  model_top_n_hit_rate?: number | null;
  expert_top_n_hit_rate?: number | null;
  model_interval_coverage_80?: number | null;
  model_interval_coverage_gap?: number | null;
  model_interval_mean_width?: number | null;
}

export interface ShowcasePlayerRow {
  player_id: string;
  player_name: string;
  position: string;
  nfl_team?: string;
  model_points: number;
  expert_points?: number | null;
  actual_points: number;
  model_q10?: number | null;
  model_q90?: number | null;
  model_rank: number;
  expert_rank: number;
  actual_rank: number;
  model_abs_error: number;
  expert_abs_error?: number | null;
  model_rank_error: number;
  expert_rank_error: number;
  rank_edge_vs_expert: number;
  point_edge_vs_expert?: number | null;
}

export interface ShowcaseIndexResponse {
  authority: 'evaluation_only';
  may_change_production_decisions: false;
  available: boolean;
  seasons: Array<{ season: number; weeks: number[]; latest_week: number }>;
}

export interface ShowcaseSeasonWeek {
  week: number;
  artifact_id: string;
  winner: ShowcaseWinner;
  primary_comparison_metric: string;
  model_mae?: number | null;
  expert_mae?: number | null;
  model_rank_mae?: number | null;
  expert_rank_mae?: number | null;
  model_spearman?: number | null;
  expert_spearman?: number | null;
  rows?: number;
}

export interface ShowcaseSeasonResponse {
  authority: 'evaluation_only';
  may_change_production_decisions: false;
  season: number;
  weeks: ShowcaseSeasonWeek[];
  record: {
    model_wins: number;
    expert_wins: number;
    ties: number;
    unavailable: number;
  };
}

export interface ShowcaseWeekResponse {
  authority: 'evaluation_only';
  may_change_production_decisions: false;
  manifest: {
    artifact_id: string;
    season: number;
    week: number;
    scoring: string;
    authority: string;
    generated_at_utc: string;
    rows: number;
    snapshots: Record<string, { source: string; captured_at_utc: string; source_path?: string | null }>;
  };
  metrics: {
    winner: ShowcaseWinner;
    primary_comparison_metric: string;
    overall: ShowcaseScopeMetrics;
    positions: Record<string, ShowcaseScopeMetrics>;
    position_battles: Record<string, { winner: ShowcaseWinner; metric: string }>;
  };
  narrative: {
    headline: string;
    winner: ShowcaseWinner;
    winner_metric: string;
    model_position_wins: string[];
    expert_position_wins: string[];
    best_calls: ShowcasePlayerRow[];
    biggest_misses: ShowcasePlayerRow[];
  };
  players: ShowcasePlayerRow[];
  filters?: { position?: string | null; limit?: number };
}
