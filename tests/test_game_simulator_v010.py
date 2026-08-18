from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from player_state_engine.api.operational import create_app
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from player_state_engine.game_intelligence.simulator import simulate_matchup
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles
from tests.test_game_intelligence_v010 import player_map, synthetic_pbp


def _research_inputs():
    plays = build_play_intelligence_frame(synthetic_pbp())
    tendencies = build_team_tendency_snapshots(plays)
    enriched = attach_point_in_time_matchup_features(plays, tendencies)
    chronology = enriched["season"] * 25 + enriched["week"]
    train = enriched.loc[chronology < 2026 * 25 + 2]
    play_model = PlayCallModel().fit(train)
    outcome_model = EmpiricalPlayOutcomeModel(min_stratum_plays=2).fit(train)
    usage = build_player_usage_profiles(
        plays,
        season=2026,
        week=2,
        players=player_map(),
    )
    return tendencies, usage, play_model, outcome_model


def test_play_by_play_simulation_is_seeded_and_exactly_rescored() -> None:
    tendencies, usage, play_model, outcome_model = _research_inputs()
    matchup = MatchupSpec(
        season=2026,
        week=2,
        home_team="AAA",
        away_team="BBB",
        game_id="2026_02_BBB_AAA",
        home_spread=-3.0,
        game_total=47.5,
    )
    # Unit tests need diverse state transitions, not production Monte Carlo volume.
    config = SimulationConfig(simulations=6, max_plays=60, seed=19)
    league = LeagueConfig(scoring="ppr")
    first = simulate_matchup(
        matchup,
        tendencies=tendencies,
        usage=usage,
        outcome_model=outcome_model,
        play_call_model=play_model,
        league_config=league,
        config=config,
    )
    second = simulate_matchup(
        matchup,
        tendencies=tendencies,
        usage=usage,
        outcome_model=outcome_model,
        play_call_model=play_model,
        league_config=league,
        config=config,
    )

    pd.testing.assert_frame_equal(first.game_draws, second.game_draws)
    pd.testing.assert_frame_equal(first.team_draws, second.team_draws)
    assert not first.player_draws.empty
    assert "league_fantasy_points" in first.player_draws
    assert first.diagnostics["simulation_scoring_source"] == "exact_league"
    assert first.diagnostics["promoted"] is False
    assert first.team_draws["game_id"].eq("2026_02_BBB_AAA").all()
    assert set(first.team_draws["team"]) == {"AAA", "BBB"}


def test_research_api_fails_closed_without_game_artifact(tmp_path) -> None:
    app = create_app(
        store_root=tmp_path / "leagues",
        projections_path=tmp_path / "missing.csv",
        ranking_root=tmp_path / "rankings",
        game_intelligence_root=tmp_path / "game-intelligence",
        game_intelligence_registry=tmp_path / "registry.json",
    )
    client = TestClient(app)
    status = client.get("/v1/research/game-intelligence/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["artifact_available"] is False
    assert payload["automatic_promotion"] is False
    assert payload["production_projection_changed"] is False

    sources = client.get("/v1/research/game-intelligence/sources")
    assert sources.status_code == 200
    assert sources.json()["retrospective_sources_allowed_in_live_prediction"] is False

    simulation = client.post(
        "/v1/research/game-intelligence/simulate",
        json={
            "season": 2026,
            "week": 1,
            "home_team": "AAA",
            "away_team": "BBB",
        },
    )
    assert simulation.status_code == 503
