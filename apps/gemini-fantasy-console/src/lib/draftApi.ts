import type {
  DraftBoardPlayer,
  DraftBoardResponse,
  DraftCompareResponse,
  DraftLeagueSummary,
  DraftPlanResponse,
  RankingAuditResponse,
} from '../../shared/draft-types';

export interface DraftReliabilityFields {
  guarded_draft_action?: string;
  draft_reliability_score?: number;
  draft_reliability?: 'LOW' | 'MEDIUM' | 'HIGH' | string;
  draft_reliability_reasons?: string;
  room_survival_to_next_pick?: number;
  room_survival_standard_error?: number;
  room_position_wait_value?: number;
  room_position_wait_loss?: number;
  room_expected_position_supply_next_pick?: number;
  room_challenger_score?: number;
  room_rank?: number;
  room_rank_delta?: number;
  room_vs_baseline_survival_gap?: number;
  projection_freshness_status?: string;
  projection_freshness_score?: number;
  projection_freshness_hard_fail?: boolean;
}

export type ReliableDraftPlayer = DraftBoardPlayer & DraftReliabilityFields;

export interface ReliableDraftBoardResponse extends Omit<DraftBoardResponse, 'board'> {
  board: ReliableDraftPlayer[];
  readiness?: {
    score: number;
    ready: boolean;
    flags: string[];
    required_positions: string[];
    missing_positions: string[];
    projection_rows: number;
    unique_player_coverage: number;
    market_adp_coverage: number;
    exact_scoring_coverage: number;
    valuation_coverage: number;
  };
  research?: {
    room_challenger_promoted: boolean;
    room_simulations: number;
    baseline_survival_authoritative: boolean;
    purpose: string;
  };
}

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

  reliableBoard: (
    leagueId: string,
    rosterId: string,
    options: {
      draftSlot?: number;
      totalRounds?: number;
      refresh?: boolean;
      forceRefresh?: boolean;
      limit?: number;
      roomSimulations?: number;
      maxProjectionAgeHours?: number;
      signal?: AbortSignal;
    } = {},
  ) => request<ReliableDraftBoardResponse>(
    `/v1/leagues/${encodeURIComponent(leagueId)}/draft/reliable-board${query({
      roster_id: rosterId,
      draft_slot: options.draftSlot,
      total_rounds: options.totalRounds,
      refresh: options.refresh ?? true,
      force_refresh: options.forceRefresh ?? false,
      limit: options.limit ?? 250,
      room_simulations: options.roomSimulations ?? 600,
      max_projection_age_hours: options.maxProjectionAgeHours ?? 24,
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
