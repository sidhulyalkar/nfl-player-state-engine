from __future__ import annotations

from types import SimpleNamespace

from player_state_engine.integrations.espn import ESPNImporter
from player_state_engine.integrations.portfolio import league_config_from_snapshot


class ModernFakeLeague:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.nfl_week = 1
        self.settings = SimpleNamespace(
            name="Modern ESPN Test",
            team_count=8,
            position_slot_counts={
                "QB": 2,
                "RB": 3,
                "WR": 3,
                "TE": 1,
                "OP": 1,
                "BE": 6,
            },
            scoring_format=[
                {"id": 3, "abbr": "PY", "label": "Passing Yards", "points": 0.04},
                {"id": 4, "abbr": "PTD", "label": "TD Pass", "points": 4.0},
                {"id": 20, "abbr": "INT", "label": "Interceptions Thrown", "points": -2.0},
                {"id": 24, "abbr": "RY", "label": "Rushing Yards", "points": 0.1},
                {"id": 25, "abbr": "RTD", "label": "Rushing TD", "points": 6.0},
                {"id": 53, "abbr": "REC", "label": "Each Reception", "points": 1.0},
                {"id": 42, "abbr": "REY", "label": "Receiving Yards", "points": 0.1},
                {"id": 43, "abbr": "RETD", "label": "Receiving TD", "points": 6.0},
            ],
        )
        self.teams = [
            SimpleNamespace(
                team_id=index,
                team_name=f"Team {index}",
                owners=[f"owner{index}"],
                roster=[],
                wins=0,
                losses=0,
                ties=0,
                points_for=0,
                points_against=0,
            )
            for index in range(1, 9)
        ]
        self.draft = []

    def free_agents(self, size=300):
        return []


def test_modern_espn_settings_are_applied_to_league_config() -> None:
    def factory(**kwargs):
        return ModernFakeLeague(**kwargs)

    snapshot = ESPNImporter(league_factory=factory).import_league(
        "456", season=2026, include_free_agents=False
    )
    assert snapshot.settings.roster_positions.count("QB") == 2
    assert snapshot.settings.roster_positions.count("OP") == 1
    assert snapshot.settings.scoring["REC"] == 1.0
    assert snapshot.settings.superflex is True

    config = league_config_from_snapshot(snapshot)
    assert config.teams == 8
    assert config.roster_slots["QB"] == 2
    assert config.roster_slots["SUPER_FLEX"] == 1
    assert config.roster_slots["WR"] == 3
    assert config.scoring == "ppr"
    assert config.scoring_weights["passing_yards"] == 0.04
    assert config.scoring_weights["passing_tds"] == 4.0
    assert config.scoring_weights["interceptions"] == -2.0
    assert config.scoring_weights["receptions"] == 1.0
