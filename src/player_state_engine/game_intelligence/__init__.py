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
from player_state_engine.game_intelligence.decision import (
    DriveTerminationHazardModel,
    FourthDownDecisionModel,
    evaluate_fourth_down_scores,
    evaluate_fourth_down_team_draws,
    evaluate_termination_scores,
    extract_drive_termination_events,
    extract_fourth_down_decisions,
    legacy_fourth_down_probabilities,
    observed_fourth_down_team_games,
    permute_fourth_down_actions_within_context_season,
    permute_termination_targets_within_context_season,
)
from player_state_engine.game_intelligence.decision_benchmark import (
    DecisionBenchmarkResult,
    recommend_v016_development,
    run_v015_decision_benchmark,
    v015_decision_promotion_gate,
)
from player_state_engine.game_intelligence.decision_simulator import (
    simulate_matchup_decision_probe,
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
from player_state_engine.game_intelligence.terminal import (
    TERMINAL_FAMILIES,
    TerminalFamilyModel,
    attach_terminal_family_labels,
    evaluate_terminal_family_scores,
    evaluate_terminal_family_team_draws,
    extract_terminal_family_events,
    observed_terminal_family_team_games,
    permute_conditional_terminal_families_within_context_season,
    permute_terminal_families_within_context_season,
)
from player_state_engine.game_intelligence.terminal_benchmark import (
    TerminalBenchmarkResult,
    recommend_v017_development,
    run_v016_terminal_benchmark,
    v016_terminal_promotion_gate,
)
from player_state_engine.game_intelligence.terminal_simulator import (
    simulate_matchup_terminal_probe,
)
from player_state_engine.game_intelligence.transition import (
    PossessionTransitionModel,
    build_possession_transition_frame,
    evaluate_field_goal_scores,
    evaluate_transition_event_scores,
    evaluate_transition_team_draws,
    extract_field_goal_attempts,
    observed_transition_team_games,
    permute_field_goal_results_within_distance_season,
    permute_transition_targets_within_type_season,
)
from player_state_engine.game_intelligence.transition_benchmark import (
    TransitionBenchmarkResult,
    recommend_v015_development,
    run_v014_transition_benchmark,
    v014_transition_promotion_gate,
)
from player_state_engine.game_intelligence.transition_simulator import (
    simulate_matchup_transition_probe,
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
    "DecisionBenchmarkResult",
    "DriveTerminationHazardModel",
    "DriveVolumeBenchmarkResult",
    "DriveVolumeModel",
    "EmpiricalPlayOutcomeModel",
    "ExpandingGameBenchmarkResult",
    "FactorialBenchmarkResult",
    "FourthDownDecisionModel",
    "PlayCallModel",
    "PossessionTransitionModel",
    "QuantileBlendCalibrator",
    "StateConditionedOpportunityModel",
    "TERMINAL_FAMILIES",
    "TerminalBenchmarkResult",
    "TerminalFamilyModel",
    "TransitionBenchmarkResult",
    "attach_terminal_family_labels",
    "build_coaching_matchup_history",
    "build_matchup_profile",
    "build_play_intelligence_frame",
    "build_player_usage_profiles",
    "build_possession_transition_frame",
    "build_team_tendency_snapshots",
    "evaluate_drive_volume_draws",
    "evaluate_field_goal_scores",
    "evaluate_fourth_down_scores",
    "evaluate_fourth_down_team_draws",
    "evaluate_pace_event_scores",
    "evaluate_terminal_family_scores",
    "evaluate_terminal_family_team_draws",
    "evaluate_termination_scores",
    "evaluate_transition_event_scores",
    "evaluate_transition_team_draws",
    "expanding_quantile_blend_benchmark",
    "extract_drive_frame",
    "extract_drive_termination_events",
    "extract_field_goal_attempts",
    "extract_fourth_down_decisions",
    "extract_terminal_family_events",
    "legacy_fourth_down_probabilities",
    "observed_drive_volume",
    "observed_fourth_down_team_games",
    "observed_terminal_family_team_games",
    "observed_transition_team_games",
    "permute_conditional_terminal_families_within_context_season",
    "permute_context_within_team_season",
    "permute_field_goal_results_within_distance_season",
    "permute_fourth_down_actions_within_context_season",
    "permute_pace_targets_within_team_season",
    "permute_terminal_families_within_context_season",
    "permute_termination_targets_within_context_season",
    "permute_transition_targets_within_type_season",
    "recommend_next_development",
    "recommend_v014_development",
    "recommend_v015_development",
    "recommend_v016_development",
    "recommend_v017_development",
    "run_expanding_game_benchmark",
    "run_v012_factorial_benchmark",
    "run_v013_drive_volume_benchmark",
    "run_v014_transition_benchmark",
    "run_v015_decision_benchmark",
    "run_v016_terminal_benchmark",
    "simulate_matchup",
    "simulate_matchup_decision_probe",
    "simulate_matchup_terminal_probe",
    "simulate_matchup_transition_probe",
    "simulate_matchup_volume_probe",
    "v011_research_promotion_gate",
    "v012_state_opportunity_promotion_gate",
    "v013_drive_volume_promotion_gate",
    "v014_transition_promotion_gate",
    "v015_decision_promotion_gate",
    "v016_terminal_promotion_gate",
]
