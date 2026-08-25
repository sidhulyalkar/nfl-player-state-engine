import type {
  DecisionType,
  LeagueNeedsResponse,
  LeagueSummary,
  ModelDiagnosticsResponse,
  ModelObservatoryResponse,
  NFLStateSnapshot,
  PlayerIntelligenceResponse,
  PlayerRow,
  PlayerScenarioResponse,
  PlayerShadowResponse,
  PortfolioExposureResponse,
  PowerRanking,
  ResearchPredictionsResponse,
  ResearchSummary,
  ShadowEvaluationResponse,
  TeamContextResponse,
  TradeSuggestion,
} from '../../shared/types';
import type { EvidenceFactoryResponse } from './evidenceTypes';
import type { ShadowSeasonResponse } from './shadowSeasonTypes';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/pse${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function query(params: Record<string, string | number | undefined>) {
  const values = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') values.set(key, String(value));
  });
  const encoded = values.toString();
  return encoded ? `?${encoded}` : '';
}

export const api = {
  leagues: () => request<LeagueSummary[]>('/v1/leagues'),
  intelligenceLeagues: () => request<LeagueSummary[]>('/v1/intelligence/leagues'),
  importSleeper: (leagueId: string, userId?: string) =>
    request<{ league: unknown }>('/v1/integrations/sleeper/import', {
      method: 'POST',
      body: JSON.stringify({ league_id: leagueId, user_id: userId }),
    }),
  players: (leagueId: string, decision: DecisionType = 'trade') =>
    request<PlayerRow[]>(`/v1/leagues/${encodeURIComponent(leagueId)}/players${query({ decision })}`),
  intelligencePlayers: (leagueId: string, decision: DecisionType = 'trade') =>
    request<PlayerRow[]>(
      `/v1/leagues/${encodeURIComponent(leagueId)}/intelligence/players${query({ decision })}`,
    ),
  playerIntelligence: (leagueId: string, playerId: string) =>
    request<PlayerIntelligenceResponse>(
      `/v1/leagues/${encodeURIComponent(leagueId)}/players/${encodeURIComponent(playerId)}/intelligence`,
    ),
  playerShadow: (leagueId: string, playerId: string) =>
    request<PlayerShadowResponse>(
      `/v1/leagues/${encodeURIComponent(leagueId)}/players/${encodeURIComponent(playerId)}/shadow`,
    ),
  playerScenario: (
    leagueId: string,
    playerId: string,
    controls: {
      role_multiplier: number;
      team_volume_multiplier: number;
      availability_probability?: number;
    },
  ) => request<PlayerScenarioResponse>(
    `/v1/leagues/${encodeURIComponent(leagueId)}/players/${encodeURIComponent(playerId)}/scenario`,
    { method: 'POST', body: JSON.stringify(controls) },
  ),
  portfolioExposure: () => request<PortfolioExposureResponse>('/v1/portfolio/exposure'),
  powerRankings: (leagueId: string) =>
    request<PowerRanking[]>(`/v1/leagues/${encodeURIComponent(leagueId)}/power-rankings`),
  nflState: (season: number, throughWeek?: number) =>
    request<NFLStateSnapshot>(`/v1/nfl/state${query({ season, through_week: throughWeek })}`),
  waivers: (leagueId: string, rosterId: string) =>
    request<PlayerRow[]>(`/v1/leagues/${encodeURIComponent(leagueId)}/waivers${query({ roster_id: rosterId })}`),
  lineup: (leagueId: string, rosterId: string) =>
    request<PlayerRow[]>(`/v1/leagues/${encodeURIComponent(leagueId)}/lineup${query({ roster_id: rosterId })}`),
  needs: (leagueId: string) =>
    request<LeagueNeedsResponse>(`/v1/leagues/${encodeURIComponent(leagueId)}/needs`),
  tradeSuggestions: (leagueId: string, rosterId: string) =>
    request<TradeSuggestion[]>(`/v1/leagues/${encodeURIComponent(leagueId)}/trades/suggestions${query({ roster_id: rosterId })}`),
  researchSummary: () => request<ResearchSummary>('/v1/research/summary'),
  researchPredictions: (
    season?: number,
    week?: number,
    position?: string,
    limit?: number,
    playerId?: string,
  ) => request<ResearchPredictionsResponse>(
    `/v1/research/predictions${query({ season, week, position, limit, player_id: playerId })}`,
  ),
  playerHistory: (playerId: string, limit = 200) =>
    request<ResearchPredictionsResponse>(
      `/v1/research/players/${encodeURIComponent(playerId)}/history${query({ limit })}`,
    ),
  modelDiagnostics: (target = 'fantasy_points_ppr', method = 'quantile_engine', minimumRows = 20) =>
    request<ModelDiagnosticsResponse>(
      `/v1/research/diagnostics${query({ target, method, minimum_rows: minimumRows })}`,
    ),
  modelObservatory: (target = 'fantasy_points_ppr', method = 'quantile_engine') =>
    request<ModelObservatoryResponse>(`/v1/model/observatory${query({ target, method })}`),
  shadowEvaluation: () => request<ShadowEvaluationResponse>('/v1/model/shadow-evaluation'),
  shadowSeason: (season = 2026) =>
    request<ShadowSeasonResponse>(`/v1/model/shadow-season${query({ season })}`),
  evidenceFactory: (target = 'fantasy_points_ppr') =>
    request<EvidenceFactoryResponse>(`/v1/model/evidence-factory${query({ target })}`),
  teamContext: (season?: number, week?: number) =>
    request<TeamContextResponse>(`/v1/nfl/team-context${query({ season, week })}`),
  copilot: async (message: string, leagueId?: string, rosterId?: string) => {
    const response = await fetch('/api/copilot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, leagueId, rosterId }),
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json() as Promise<{ text: string }>;
  },
};
