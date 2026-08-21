"""Second-generation latent player-state research spine.

This package is deliberately research-authority-only. It connects dynamic player roles, regime
state, coherent football-stat simulation, calibration, forecast fusion, explanations and fantasy
season decisions without replacing the frozen production champion unless evidence gates pass.
"""

from player_state_engine.state_graph.builder import PlayerStateGraphBuilder
from player_state_engine.state_graph.calibration import RecencyWeightedConditionalConformal
from player_state_engine.state_graph.coherent import PlayerStateGraphSampler
from player_state_engine.state_graph.evidence import LatentEvidenceRouter, RoutedEvidence
from player_state_engine.state_graph.experiments import (
    EvidenceTier,
    ExperimentLedger,
    ExperimentRecord,
    PairedEffect,
    PromotionPolicy,
    paired_block_bootstrap,
)
from player_state_engine.state_graph.fusion import FusionKey, HierarchicalForecastFusion
from player_state_engine.state_graph.insights import (
    PlayerIntelligenceCard,
    ProjectionAttribution,
    ScenarioResult,
    build_intelligence_card,
    compare_scenarios,
    projection_change_attribution,
    upside_path,
)
from player_state_engine.state_graph.provenance import (
    SourceAvailabilityRecord,
    filter_point_in_time,
    infer_available_at,
    validate_no_future_evidence,
)
from player_state_engine.state_graph.regime import BOUNDARY_COLUMNS, RegimeDetector
from player_state_engine.state_graph.role import ROLE_METRICS, DiscountedBetaRoleEstimator
from player_state_engine.state_graph.season_sim import (
    FantasySeasonSimulator,
    SeasonSimulationSummary,
)
from player_state_engine.state_graph.tracking_distillation import TrackingTeacherDistiller
from player_state_engine.state_graph.types import (
    AvailabilityState,
    BetaPosterior,
    DynamicRoleState,
    ExecutionState,
    ForecastQuantiles,
    PlayerLatentState,
    RegimeState,
    RoleMetricState,
    TeamVolumeState,
    UncertaintyBreakdown,
)
from player_state_engine.state_graph.uncertainty import (
    bootstrap_quantile_uncertainty,
    decompose_counterfactual_variance,
)

__all__ = [
    "AvailabilityState",
    "BOUNDARY_COLUMNS",
    "BetaPosterior",
    "DiscountedBetaRoleEstimator",
    "DynamicRoleState",
    "EvidenceTier",
    "ExecutionState",
    "ExperimentLedger",
    "ExperimentRecord",
    "FantasySeasonSimulator",
    "ForecastQuantiles",
    "FusionKey",
    "HierarchicalForecastFusion",
    "LatentEvidenceRouter",
    "PairedEffect",
    "PlayerIntelligenceCard",
    "PlayerLatentState",
    "PlayerStateGraphBuilder",
    "PlayerStateGraphSampler",
    "ProjectionAttribution",
    "PromotionPolicy",
    "ROLE_METRICS",
    "RecencyWeightedConditionalConformal",
    "RegimeDetector",
    "RegimeState",
    "RoleMetricState",
    "RoutedEvidence",
    "ScenarioResult",
    "SeasonSimulationSummary",
    "SourceAvailabilityRecord",
    "TeamVolumeState",
    "TrackingTeacherDistiller",
    "UncertaintyBreakdown",
    "bootstrap_quantile_uncertainty",
    "build_intelligence_card",
    "compare_scenarios",
    "decompose_counterfactual_variance",
    "filter_point_in_time",
    "infer_available_at",
    "paired_block_bootstrap",
    "projection_change_attribution",
    "upside_path",
    "validate_no_future_evidence",
]
