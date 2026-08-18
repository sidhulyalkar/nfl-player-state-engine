"""Point-in-time NFL game intelligence, frozen replay, and play-by-play simulation."""

from player_state_engine.game_intelligence.benchmark import (
    ExpandingGameBenchmarkResult,
    run_expanding_game_benchmark,
    v011_research_promotion_gate,
)
from player_state_engine.game_intelligence.blend import (
    BlendBenchmarkResult,
    QuantileBlendCalibrator,
    expanding_quantile_blend_benchmark,
)
from player_state_engine.game_intelligence.drive import (
    DriveVolumeModel,
    evaluate_drive_volume_draws,
    evaluate_pace_event_scores,
    extract_drive_frame,
    observed_drive_volume,
    permute_pace_targets_within_team_season,
)
from player_state_engine.game_intelligence.drive_simulator import (
    simulate_matchup_volume_probe,
)
from player_state_engine.game_intelligence.factorial import (
    FactorialBenchmarkResult,
    recommend_next_development,
    run_v012_factorial_benchmark,
    v012_state_opportunity_promotion_gate,
)
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.opportunity import (
    StateConditionedOpportunityModel,
    permute_context_within_team_season,
)
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.simulator import simulate_matchup
from player_state_engine.game_intelligence.tendencies import (
    build_coaching_matchup_history,
    build_matchup_profile,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles
from player_state_engine.game_intelligence.volume_benchmark import (
    DriveVolumeBenchmarkResult,
    recommend_v014_development,
    run_v013_drive_volume_benchmark,
    v013_drive_volume_promotion_gate,
)

__all__ = [
    "BlendBenchmarkResult",
    "DriveVolumeBenchmarkResult",
    "DriveVolumeModel",
    "EmpiricalPlayOutcomeModel",
    "ExpandingGameBenchmarkResult",
    "FactorialBenchmarkResult",
    "PlayCallModel",
    "QuantileBlendCalibrator",
    "StateConditionedOpportunityModel",
    "build_coaching_matchup_history",
    "build_matchup_profile",
    "build_play_intelligence_frame",
    "build_player_usage_profiles",
    "build_team_tendency_snapshots",
    "evaluate_drive_volume_draws",
    "evaluate_pace_event_scores",
    "expanding_quantile_blend_benchmark",
    "extract_drive_frame",
    "observed_drive_volume",
    "permute_context_within_team_season",
    "permute_pace_targets_within_team_season",
    "recommend_next_development",
    "recommend_v014_development",
    "run_expanding_game_benchmark",
    "run_v012_factorial_benchmark",
    "run_v013_drive_volume_benchmark",
    "simulate_matchup",
    "simulate_matchup_volume_probe",
    "v011_research_promotion_gate",
    "v012_state_opportunity_promotion_gate",
    "v013_drive_volume_promotion_gate",
]
