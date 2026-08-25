export interface IntelligenceActivationEntry {
  family: string;
  status: 'disabled' | 'shadow' | 'enabled' | string;
  evidence_tier?: string | null;
  experiment_id?: string | null;
  approved_by?: string | null;
  approved_at_utc?: string | null;
  automatic_promotion: boolean;
}

export interface IntelligenceActivationSummary {
  automatic_promotion: boolean;
  families: Record<string, IntelligenceActivationEntry>;
  enabled: string[];
  shadow: string[];
  disabled: string[];
}

export interface StructuredIntelligenceState {
  player_id: string;
  latent_state: string;
  domains: string[];
  as_of_utc: string;
  latest_available_at_utc?: string | null;
  claim_count: number;
  source_count: number;
  high_authority_claim_count: number;
  speculation_claim_count: number;
  consensus_signal: number;
  support_strength: number;
  conflict_score: number;
  positive_support: number;
  negative_support: number;
  production_feature_enabled: boolean;
  authority: string;
}

export interface StructuredIntelligenceResponse {
  data_mode: 'STRUCTURED_EVIDENCE' | 'UNAVAILABLE' | string;
  authority: string;
  automatic_promotion: boolean;
  as_of_utc: string;
  filters?: { player_id?: string | null; domain?: string | null };
  health: {
    root: string;
    integrity_verified: boolean;
    integrity_failures: string[];
    claim_count: number;
    manifest_available: boolean;
    activation?: IntelligenceActivationSummary | null;
  };
  activation?: IntelligenceActivationSummary | null;
  reason?: string;
  claim_count?: number;
  effective_claim_count?: number;
  state_count?: number;
  summary?: {
    mean_conflict_score: number | null;
    max_conflict_score: number | null;
    states_with_conflict: number;
    production_feature_enabled: boolean;
  };
  states: StructuredIntelligenceState[];
}
