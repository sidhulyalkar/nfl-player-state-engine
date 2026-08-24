export interface ShadowSeasonMetrics {
  n: number;
  q50_mae?: number;
  mean_pinball?: number;
  q10_pinball?: number;
  q50_pinball?: number;
  q90_pinball?: number;
  interval_80_coverage?: number;
  mean_interval_width?: number;
  calibration_cdf_q10?: number;
  calibration_cdf_q50?: number;
  calibration_cdf_q90?: number;
}

export interface ShadowSeasonCheckpointSummary {
  checkpoint: string;
  snapshots: number;
  settled_snapshots: number;
  forecast_rows: number;
  settled_rows: number;
  production: ShadowSeasonMetrics;
  challenger: ShadowSeasonMetrics;
}

export interface ShadowSeasonPositionSummary {
  position: string;
  n: number;
  production: ShadowSeasonMetrics;
  challenger: ShadowSeasonMetrics;
}

export interface ShadowSeasonResponse {
  data_mode: 'LIVE_SHADOW' | 'UNAVAILABLE' | string;
  authority: {
    production: string;
    challenger: string;
    promotion_is_automatic: boolean;
    settlement_is_evaluation_only: boolean;
  };
  health: {
    root: string;
    season?: number | null;
    integrity_verified: boolean;
    integrity_failures: string[];
    snapshot_count: number;
    settlement_count: number;
  };
  season?: number | null;
  snapshot_count: number;
  settlement_count: number;
  overall: {
    production: ShadowSeasonMetrics;
    challenger: ShadowSeasonMetrics;
  };
  by_checkpoint: ShadowSeasonCheckpointSummary[];
  by_position: ShadowSeasonPositionSummary[];
  unsettled_snapshot_ids: string[];
}
