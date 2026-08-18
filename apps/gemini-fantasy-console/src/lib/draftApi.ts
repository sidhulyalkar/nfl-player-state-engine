import type {
  DraftBoardResponse,
  DraftCompareResponse,
  DraftLeagueSummary,
  DraftPlanResponse,
  RankingAuditResponse,
} from '../../shared/draft-types';

export class DraftApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = 'DraftApiError';
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/pse${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    let body: unknown = text;
    try { body = JSON.parse(text); } catch { /* keep text */ }
    throw new DraftApiError(response.status, text || response.statusText, body);
  }
  return response.json() as Promise<T>;
}

function query(params: Record<string, string | number | boolean | undefined>) {
  const values = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') values.set(key, String(value));
  });
  const encoded = values.toString();
  return encoded ? `?${encoded}` : '';
}

export const draftApi = {
  leagues: (signal?: AbortSignal) =>
    request<DraftLeagueSummary[]>('/v1/draft/leagues', { signal }),

  board: (
    leagueId: string,
    rosterId: string,
    options: {
      draftSlot?: number;
      totalRounds?: number;
      refresh?: boolean;
      forceRefresh?: boolean;
      limit?: number;
      signal?: AbortSignal;
    } = {},
  ) => request<DraftBoardResponse>(
    `/v1/leagues/${encodeURIComponent(leagueId)}/draft/board${query({
      roster_id: rosterId,
      draft_slot: options.draftSlot,
      total_rounds: options.totalRounds,
      refresh: options.refresh ?? true,
      force_refresh: options.forceRefresh ?? false,
      limit: options.limit ?? 250,
    })}`,
    { signal: options.signal },
  ),

  compare: (
    leagueId: string,
    payload: {
      roster_id: string;
      player_ids: string[];
      draft_slot?: number;
      total_rounds?: number;
      refresh?: boolean;
      force_refresh?: boolean;
      simulations?: number;
    },
    signal?: AbortSignal,
  ) => request<DraftCompareResponse>(
    `/v1/leagues/${encodeURIComponent(leagueId)}/draft/compare`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  ),

  rankingAudit: (leagueId: string, signal?: AbortSignal) =>
    request<RankingAuditResponse>(
      `/v1/leagues/${encodeURIComponent(leagueId)}/rankings/audit?limit=500`,
      { signal },
    ),

  plan: (
    leagueId: string,
    payload: {
      roster_id: string;
      player_ids: string[];
      draft_slot?: number;
      total_rounds?: number;
      refresh?: boolean;
      force_refresh?: boolean;
      simulations?: number;
    },
    signal?: AbortSignal,
  ) => request<DraftPlanResponse>(
    `/v1/leagues/${encodeURIComponent(leagueId)}/draft/plan`,
    { method: 'POST', body: JSON.stringify(payload), signal },
  ),
};
