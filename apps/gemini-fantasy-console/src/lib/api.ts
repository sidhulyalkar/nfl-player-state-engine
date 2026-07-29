import type {
  DecisionType,
  LeagueNeedsResponse,
  LeagueSummary,
  NFLStateSnapshot,
  PlayerRow,
  PowerRanking,
  ResearchPredictionsResponse,
  ResearchSummary,
  TeamContextResponse,
  TradeSuggestion,
} from '../../shared/types';

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
  importSleeper: (leagueId: string, userId?: string) =>
    request<{ league: unknown }>('/v1/integrations/sleeper/import', {
      method: 'POST',
      body: JSON.stringify({ league_id: leagueId, user_id: userId }),
    }),
  players: (leagueId: string, decision: DecisionType = 'trade') =>
    request<PlayerRow[]>(`/v1/leagues/${encodeURIComponent(leagueId)}/players${query({ decision })}`),
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
  researchPredictions: (season?: number, week?: number, position?: string, limit?: number) =>
    request<ResearchPredictionsResponse>(`/v1/research/predictions${query({ season, week, position, limit })}`),
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
