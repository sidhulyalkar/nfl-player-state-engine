from player_state_engine.integrations.sleeper import SleeperImporter


class FakeClient:
    def get_json(self, url: str):
        if url.endswith("/league/L1"):
            return {
                "league_id": "L1",
                "name": "Lab League",
                "season": "2026",
                "total_rosters": 2,
                "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "BN"],
                "scoring_settings": {"rec": 1.0},
                "settings": {"waiver_budget": 100, "playoff_week_start": 15},
                "status": "in_season",
            }
        if url.endswith("/league/L1/rosters"):
            return [
                {
                    "roster_id": 1,
                    "owner_id": "u1",
                    "players": ["p1"],
                    "starters": ["p1"],
                    "reserve": [],
                    "settings": {"wins": 2, "losses": 1, "fpts": 300},
                },
                {
                    "roster_id": 2,
                    "owner_id": "u2",
                    "players": ["p2"],
                    "starters": ["p2"],
                    "reserve": [],
                    "settings": {"wins": 1, "losses": 2, "fpts": 250},
                },
            ]
        if url.endswith("/league/L1/users"):
            return [
                {"user_id": "u1", "display_name": "Sid", "metadata": {"team_name": "Neural Blitz"}},
                {"user_id": "u2", "display_name": "Rival", "metadata": {"team_name": "Other Team"}},
            ]
        if url.endswith("/league/L1/traded_picks"):
            return [{"season": "2027", "round": 1, "roster_id": 1, "owner_id": 2}]
        if url.endswith("/state/nfl"):
            return {"season": "2026", "week": 4}
        if url.endswith("/players/nfl"):
            return {
                "p1": {
                    "full_name": "Alpha QB",
                    "fantasy_positions": ["QB"],
                    "team": "SF",
                    "active": True,
                    "gsis_id": "g1",
                },
                "p2": {
                    "full_name": "Beta RB",
                    "fantasy_positions": ["RB"],
                    "team": "DET",
                    "active": True,
                    "gsis_id": "g2",
                },
                "p3": {
                    "full_name": "Free WR",
                    "fantasy_positions": ["WR"],
                    "team": "NYG",
                    "active": True,
                    "gsis_id": "g3",
                },
            }
        raise AssertionError(url)


def test_sleeper_import_normalizes_league():
    snapshot = SleeperImporter(FakeClient()).import_league("L1")
    assert snapshot.identity.name == "Lab League"
    assert snapshot.settings.current_week == 4
    assert snapshot.roster("1").team_name == "Neural Blitz"
    assert snapshot.roster("1").players[0].canonical_player_id == "g1"
    assert snapshot.free_agents[0].player_name == "Free WR"
    assert snapshot.draft_picks[0].round == 1
