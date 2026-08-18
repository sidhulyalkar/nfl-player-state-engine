from __future__ import annotations

from collections import Counter

from player_state_engine.integrations.sleeper import SleeperImporter


class FakeClient:
    def __init__(self) -> None:
        self.calls = Counter()

    def get_json(self, url: str):
        path = url.split("/v1/", 1)[1]
        self.calls[path] += 1
        if path == "state/nfl":
            return {"season": "2026", "week": 1}
        if path == "user/sid":
            return {"user_id": "u1", "username": "sid"}
        if path == "user/u1":
            return {"user_id": "u1", "username": "sid"}
        if path == "user/u1/leagues/nfl/2026":
            return [{"league_id": "L1"}, {"league_id": "L2"}]
        if path == "players/nfl":
            return {
                "p1": {
                    "active": True,
                    "full_name": "Player One",
                    "fantasy_positions": ["RB"],
                    "team": "SF",
                },
                "p2": {
                    "active": True,
                    "full_name": "Player Two",
                    "fantasy_positions": ["WR"],
                    "team": "DET",
                },
            }
        if path.startswith("league/") and path.count("/") == 1:
            lid = path.split("/")[1]
            return {
                "league_id": lid,
                "name": lid,
                "season": "2026",
                "total_rosters": 1,
                "roster_positions": ["QB", "RB", "WR", "FLEX", "BN"],
                "settings": {},
                "scoring_settings": {"rec": 1.0},
            }
        if path.endswith("/rosters"):
            return [
                {
                    "roster_id": 1,
                    "owner_id": "u1",
                    "players": ["p1"],
                    "starters": ["p1"],
                    "settings": {},
                }
            ]
        if path.endswith("/users"):
            return [{"user_id": "u1", "display_name": "Sid", "metadata": {}}]
        if path.endswith("/traded_picks"):
            return []
        if "/matchups/" in path:
            return []
        if path.endswith("/drafts"):
            return []
        raise AssertionError(path)


def test_username_sync_imports_all_leagues_and_reuses_player_map() -> None:
    client = FakeClient()
    importer = SleeperImporter(client=client)
    snapshots = importer.import_user_leagues("sid", season=2026)
    assert [snapshot.identity.league_id for snapshot in snapshots] == ["L1", "L2"]
    assert client.calls["players/nfl"] == 1
    assert all(snapshot.metadata["external_roster_id"] == "1" for snapshot in snapshots)
