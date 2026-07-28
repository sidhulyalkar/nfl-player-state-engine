import pandas as pd

from player_state_engine.product.league_picture import (
    attach_ownership,
    league_power_rankings,
    roster_needs,
)
from player_state_engine.product.schemas import (
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
    RosterEntry,
)


def snapshot():
    return LeagueSnapshot(
        identity=LeagueIdentity(league_id="L", platform="demo", name="Demo", season=2026),
        settings=LeagueSettings(teams=2, season=2026),
        rosters=[
            FantasyRoster(
                roster_id="1",
                team_name="A",
                players=[RosterEntry(platform_player_id="x1", canonical_player_id="p1")],
            ),
            FantasyRoster(
                roster_id="2",
                team_name="B",
                players=[RosterEntry(platform_player_id="x2", canonical_player_id="p2")],
            ),
        ],
    )


def values():
    return pd.DataFrame(
        [
            {
                "player_id": "p1",
                "player_name": "One",
                "position": "RB",
                "decision_value": 20,
                "floor_vorp": 10,
                "upside_vorp": 30,
                "uncertainty": 20,
            },
            {
                "player_id": "p2",
                "player_name": "Two",
                "position": "WR",
                "decision_value": 18,
                "floor_vorp": 9,
                "upside_vorp": 28,
                "uncertainty": 19,
            },
            {
                "player_id": "p3",
                "player_name": "Three",
                "position": "QB",
                "decision_value": 15,
                "floor_vorp": 8,
                "upside_vorp": 20,
                "uncertainty": 12,
            },
        ]
    )


def test_ownership_power_and_needs():
    owned = attach_ownership(values(), snapshot())
    assert owned.loc[owned.player_id.eq("p1"), "owner_team_name"].iloc[0] == "A"
    assert bool(owned.loc[owned.player_id.eq("p3"), "is_free_agent"].iloc[0])
    power = league_power_rankings(snapshot(), values())
    assert set(power.team_name) == {"A", "B"}
    needs = roster_needs(snapshot(), values())
    assert len(needs) == 8
