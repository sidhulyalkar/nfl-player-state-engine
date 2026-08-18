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
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.opportunity import StateConditionedOpportunityModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.simulator import simulate_matchup
from player_state_engine.game_intelligence.tendencies import (
    build_coaching_matchup_history,
    build_matchup_profile,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles

__all__ = [
    "BlendBenchmarkResult",
    "EmpiricalPlayOutcomeModel",
    "ExpandingGameBenchmarkResult",
    "PlayCallModel",
    "QuantileBlendCalibrator",
    "StateConditionedOpportunityModel",
    "build_coaching_matchup_history",
    "build_matchup_profile",
    "build_play_intelligence_frame",
    "build_player_usage_profiles",
    "build_team_tendency_snapshots",
    "expanding_quantile_blend_benchmark",
    "run_expanding_game_benchmark",
    "simulate_matchup",
    "v011_research_promotion_gate",
]
