export type NavPage =
  | 'overview'
  | 'league'
  | 'players'
  | 'trade'
  | 'waivers'
  | 'lineup'
  | 'nfl'
  | 'model';

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
  decision_specific_score?: number;
  fantasy_points_ppr_q10?: number;
  fantasy_points_ppr_q50?: number;
  fantasy_points_ppr_q90?: number;
  season_points_q10?: number;
  season_points_q50?: number;
  season_points_q90?: number;
  availability_probability?: number;
  opportunity_confidence?: number;
  breakout_probability?: number;
  decision_reasons?: string;
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

export interface TradeSuggestion {
  explanation: string;
  analysis: {
    fairness_score: number;
    mutual_benefit_score: number;
    confidence: number;
    verdict: string;
    side_a: { roster_id: string; value_delta: number; starter_delta: number; reasons: string[] };
    side_b: { roster_id: string; value_delta: number; starter_delta: number; reasons: string[] };
  };
  trade: unknown;
}

export interface NFLTeamState {
  team: string; wins: number; losses: number; ties: number; points_for: number; points_against: number; point_differential: number; win_percentage: number; streak?: string | null;
}

export interface NFLStateSnapshot { season: number; week?: number | null; teams: NFLTeamState[]; }
