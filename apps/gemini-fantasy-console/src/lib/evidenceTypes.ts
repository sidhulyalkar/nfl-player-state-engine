export interface EvidenceMethodSummaryRow {
  target: string;
  method: string;
  rows?: number;
  available_rows?: number;
  evaluable_outcome_rows?: number;
  valid_rate?: number;
  prediction_cutoff_rate?: number;
  mean_pinball?: number;
  pinball_q10?: number;
  pinball_q50?: number;
  pinball_q90?: number;
  q50_mae?: number;
  q50_bias?: number;
  empirical_80_coverage?: number;
  coverage_gap?: number;
  mean_interval_width_80?: number;
  crossed_quantile_rate?: number;
}

export interface EvidencePairComparisonRow {
  experiment_id: string;
  target: string;
  champion: string;
  challenger: string;
  paired_rows: number;
  paired_seasons: number;
  overlap_rate: number;
  data_availability: number;
  champion_mean_pinball: number;
  challenger_mean_pinball: number;
  pinball_effect_champion_minus_challenger: number;
  ci_low: number | null;
  ci_high: number | null;
  probability_improves: number | null;
  p_value: number | null;
  fdr_q_value: number | null;
  champion_q50_mae: number;
  challenger_q50_mae: number;
  champion_80_coverage: number;
  challenger_80_coverage: number;
  champion_mean_width_80: number;
  challenger_mean_width_80: number;
  challenger_crossed_quantile_rate: number;
  season_consistency: number;
  position_consistency: number;
  week_consistency: number;
  evidence_tier: number;
  promotion_status: string;
  blockers: string;
}

export interface EvidenceExperimentRow {
  experiment_id: string;
  challenger: string;
  champion: string;
  primary_metric: string;
  evidence_tier: number;
  effect: number;
  ci_low?: number | null;
  ci_high?: number | null;
  p_value?: number | null;
  fdr_q_value?: number | null;
  promoted: boolean;
  blockers: string | string[];
}

export interface EvidenceNegativeControlRow {
  target: string;
  method: string;
  control_method: string;
  rows: number;
  singleton_groups: number;
  groups: number;
  real_mean_pinball: number;
  control_mean_pinball: number;
  effect_control_minus_real: number;
  ci_low: number | null;
  ci_high: number | null;
  probability_real_improves: number | null;
  passed: boolean;
}

export interface EvidenceFactoryResponse {
  data_mode: string;
  authority: string;
  reason?: string;
  target?: string | null;
  health: {
    available: boolean;
    available_count: number;
    expected_count: number;
    missing: string[];
    integrity_verified?: boolean;
    integrity_failures?: string[];
    artifacts?: Record<string, Record<string, unknown>>;
  };
  manifest?: {
    schema_version?: number;
    authority?: string;
    git_sha?: string | null;
    champion_method?: string;
    default_champion_method?: string;
    champion_methods?: Record<string, string>;
    targets?: string[];
    created_at_utc?: string;
    graph?: Record<string, unknown>;
    negative_control?: Record<string, unknown>;
    multiple_testing?: Record<string, unknown>;
  } | null;
  method_summary?: EvidenceMethodSummaryRow[];
  slice_metrics?: Array<Record<string, string | number | boolean | null>>;
  paired_comparisons?: EvidencePairComparisonRow[];
  experiment_ledger?: EvidenceExperimentRow[];
  negative_controls?: EvidenceNegativeControlRow[];
  promotion?: {
    automatic: boolean;
    production_champion: string;
    default_champion_method?: string;
    champion_methods?: Record<string, string>;
    note: string;
  };
}
