from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.opportunity import rank_high_chance_opportunities
from player_state_engine.fantasy.valuation import value_players


def test_league_specific_value_and_opportunity_rank() -> None:
    projections = pd.DataFrame(
        {
            "player_id": ["a", "b", "c", "d"],
            "player_name": ["A", "B", "C", "D"],
            "position": ["RB", "RB", "WR", "WR"],
            "season_points_q10": [120, 80, 100, 90],
            "season_points_q50": [200, 140, 180, 150],
            "season_points_q90": [280, 210, 250, 220],
        }
    )
    valued = value_players(
        projections, LeagueConfig(teams=1, roster_slots={"RB": 1, "WR": 1, "FLEX": 0, "BENCH": 0})
    )
    assert valued.iloc[0].player_name in {"A", "C"}
    opportunities = rank_high_chance_opportunities(
        pd.DataFrame(
            {
                "player_name": ["A", "B"],
                "opportunity_active_probability": [0.95, 0.8],
                "opportunity_target_share_q50": [0.25, 0.05],
                "opportunity_carry_share_q50": [0.05, 0.05],
                "opportunity_snap_share_q50": [0.9, 0.5],
                "opportunity_route_participation_q50": [0.85, 0.4],
            }
        )
    )
    assert opportunities.iloc[0].player_name == "A"


def test_lineup_optimizer_respects_flex() -> None:
    from player_state_engine.fantasy.decisions import optimize_lineup

    players = pd.DataFrame(
        {
            "player_name": ["QB", "RB1", "RB2", "WR1", "WR2", "TE"],
            "position": ["QB", "RB", "RB", "WR", "WR", "TE"],
            "lineup_score": [20, 15, 14, 18, 13, 10],
        }
    )
    cfg = LeagueConfig(teams=1, roster_slots={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "FLEX": 1})
    lineup = optimize_lineup(players, cfg)
    assert len(lineup) == 5
    assert "RB2" in set(lineup.player_name)
