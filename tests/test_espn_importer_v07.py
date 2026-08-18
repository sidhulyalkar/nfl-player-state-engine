from __future__ import annotations

from types import SimpleNamespace

from player_state_engine.integrations.espn import ESPNImporter


class FakeLeague:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.nfl_week = 1
        self.settings = SimpleNamespace(
            name="ESPN Test",
            team_count=2,
            roster_settings={"QB": 2, "RB": 3, "WR": 3, "FLEX": 3, "BE": 5},
            scoring_format={"PPR": 1.0},
        )
        player = SimpleNamespace(
            playerId=101,
            name="Quarter Back",
            position="QB",
            proTeam="SF",
            lineupSlot="QB",
        )
        self.teams = [
            SimpleNamespace(
                team_id=1,
                team_name="One",
                owners=["owner1"],
                roster=[player],
                wins=0,
                losses=0,
                ties=0,
                points_for=0,
                points_against=0,
            ),
            SimpleNamespace(
                team_id=2,
                team_name="Two",
                owners=["owner2"],
                roster=[],
                wins=0,
                losses=0,
                ties=0,
                points_for=0,
                points_against=0,
            ),
        ]
        self.draft = []

    def free_agents(self, size=300):
        return []


def test_espn_private_credentials_are_used_but_never_serialized(monkeypatch) -> None:
    monkeypatch.setenv("PSE_ESPN_S2", "top-secret-s2")
    monkeypatch.setenv("PSE_ESPN_SWID", "{top-secret-swid}")
    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return FakeLeague(**kwargs)

    snapshot = ESPNImporter(league_factory=factory).import_league("123", season=2026)
    assert captured["espn_s2"] == "top-secret-s2"
    assert snapshot.identity.platform == "espn"
    assert snapshot.settings.teams == 2
    payload = snapshot.model_dump_json()
    assert "top-secret-s2" not in payload
    assert "top-secret-swid" not in payload
    assert snapshot.metadata["credentials_present"] is True
