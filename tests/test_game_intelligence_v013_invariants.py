from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.drive import evaluate_drive_volume_draws
from player_state_engine.game_intelligence.drive_simulator import simulate_matchup_volume_probe
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from tests.test_game_intelligence_v013 import _research_inputs


def test_simulated_drive_counts_require_at_least_one_scrimmage_play() -> None:
    (
        _,
        tendencies,
        usage,
        play_model,
        outcome_model,
        opportunity_model,
        drive_model,
    ) = _research_inputs()
    matchup = MatchupSpec(
        season=2026,
        week=2,
        home_team="AAA",
        away_team="BBB",
        game_id="2026_02_BBB_AAA",
    )
    result = simulate_matchup_volume_probe(
        matchup,
        tendencies=tendencies,
        usage=usage,
        outcome_model=outcome_model,
        play_call_model=play_model,
        opportunity_model=opportunity_model,
        drive_volume_model=drive_model,
        league_config=LeagueConfig(),
        config=SimulationConfig(simulations=4, max_plays=40, seed=91),
    )
    assert (result.team_draws["drives"] <= result.team_draws["plays"]).all()
    assert result.diagnostics["drive_count_estimand"] == (
        "possessions with at least one scrimmage play"
    )
    assert result.diagnostics["seconds_per_play_estimand"] == (
        "continuing-drive forward runoff"
    )


def test_drive_volume_evaluator_fails_closed_on_incomplete_draw_schema() -> None:
    predicted = pd.DataFrame(
        {
            "game_id": ["g"],
            "team": ["A"],
            "drives": [10.0],
        }
    )
    observed = pd.DataFrame(
        {
            "game_id": ["g"],
            "team": ["A"],
            "drives": [10.0],
            "plays_per_drive": [6.0],
            "seconds_per_play": [25.0],
            "mean_start_yardline_100": [75.0],
        }
    )
    with pytest.raises(ValueError, match="Drive-volume draws missing"):
        evaluate_drive_volume_draws(predicted, observed)
