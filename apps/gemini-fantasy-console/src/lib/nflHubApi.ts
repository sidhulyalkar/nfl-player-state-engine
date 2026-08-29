export interface NflHubSourceHealth {
  source: string;
  available: boolean;
  required: boolean;
  rows: number;
  collected_at_utc: string;
  error: string | null;
}

export interface NflHubPlayerState {
  player_id: string;
  player_name?: string | null;
  team?: string | null;
  position?: string | null;
  roster_status?: string | null;
  roster_status_provenance?: string | null;
  depth_rank?: number | null;
  depth_position?: string | null;
  depth_team?: string | null;
  injury_status?: string | null;
  practice_status?: string | null;
  primary_injury?: string | null;
  market_rank?: number | null;
  market_adp?: number | null;
  projection_q50?: number | null;
  projection_vorp?: number | null;
  projection_model_version?: string | null;
}

export interface NflHubEvent {
  event_type: string;
  player_id: string | null;
  player_name: string | null;
  team: string | null;
  position: string | null;
  significance: number;
  detail: string;
  before: NflHubPlayerState | null;
  after: NflHubPlayerState | null;
  authority: string;
}

export interface NflHubGame {
  game_id?: string | null;
  game_type?: string | null;
  week?: number | null;
  away_team?: string | null;
  home_team?: string | null;
  game_date?: string | null;
}

export interface NflHubResponse {
  schema_version: number;
  authority: string;
  season: number;
  generated_at_utc: string;
  status: 'READY' | 'DEGRADED' | 'STALE' | 'UNAVAILABLE' | string;
  required_source_failures: string[];
  optional_source_failures: string[];
  source_health: NflHubSourceHealth[];
  player_count: number;
  players: NflHubPlayerState[];
  events: NflHubEvent[];
  event_count: number;
  upcoming_games: NflHubGame[];
  model_note: string;
  cache: {
    root: string;
    refreshed_this_request: boolean;
    snapshot_age_seconds: number | null;
    stale_after_seconds: number;
    stale: boolean;
  };
  refresh_warning: string | null;
  served_at_utc: string;
}

async function requestHub(refresh: boolean, signal?: AbortSignal): Promise<NflHubResponse> {
  const params = new URLSearchParams({
    season: '2026',
    refresh: String(refresh),
    max_age_minutes: '30',
  });
  const response = await fetch(`/api/pse/v1/nfl/hub?${params.toString()}`, { signal });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `NFL Hub request failed (${response.status})`);
  }
  return response.json() as Promise<NflHubResponse>;
}

export const nflHubApi = {
  snapshot: (signal?: AbortSignal) => requestHub(false, signal),
  refresh: (signal?: AbortSignal) => requestHub(true, signal),
};
