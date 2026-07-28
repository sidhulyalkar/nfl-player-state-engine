import type { LeagueSummary, NFLStateSnapshot, PlayerRow, PowerRanking, TradeSuggestion } from '../../shared/types';

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

export const api = {
  leagues: () => request<LeagueSummary[]>('/v1/leagues'),
  importSleeper: (leagueId: string, userId?: string) =>
    request<{ league: unknown }>('/v1/integrations/sleeper/import', {
      method: 'POST',
      body: JSON.stringify({ league_id: leagueId, user_id: userId }),
    }),
  players: (leagueId: string, decision = 'trade') =>
    request<PlayerRow[]>(`/v1/leagues/${leagueId}/players?decision=${decision}`),
  powerRankings: (leagueId: string) =>
    request<PowerRanking[]>(`/v1/leagues/${leagueId}/power-rankings`),
  nflState: (season: number, throughWeek?: number) =>
    request<NFLStateSnapshot>(`/v1/nfl/state?season=${season}${throughWeek ? `&through_week=${throughWeek}` : ''}`),
  waivers: (leagueId: string, rosterId: string) =>
    request<PlayerRow[]>(`/v1/leagues/${leagueId}/waivers?roster_id=${rosterId}`),
  lineup: (leagueId: string, rosterId: string) =>
    request<PlayerRow[]>(`/v1/leagues/${leagueId}/lineup?roster_id=${rosterId}`),
  tradeSuggestions: (leagueId: string, rosterId: string) =>
    request<TradeSuggestion[]>(`/v1/leagues/${leagueId}/trades/suggestions?roster_id=${rosterId}`),
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
