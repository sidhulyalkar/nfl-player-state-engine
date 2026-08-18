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
                    "gsis_id": "g1",
                },
                "p2": {
                    "active": True,
                    "full_name": "Player Two",
                    "fantasy_positions": ["WR"],
                    "team": "DET",
                    "gsis_id": "g2",
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
        if path == "league/L1/drafts":
            return [{"draft_id": "D1", "status": "drafting", "type": "snake", "settings": {}}]
        if path == "draft/D1/picks":
            return [{"player_id": "p2", "roster_id": 1, "pick_no": 1}]
        if path == "league/L2/drafts":
            return []
        raise AssertionError(path)


def test_username_sync_imports_all_leagues_and_reuses_player_map() -> None:
    client = FakeClient()
    importer = SleeperImporter(client=client)
    snapshots = importer.import_user_leagues("sid", season=2026)
    assert [snapshot.identity.league_id for snapshot in snapshots] == ["L1", "L2"]
    assert client.calls["players/nfl"] == 1
    assert all(snapshot.metadata["external_roster_id"] == "1" for snapshot in snapshots)


def test_live_draft_pick_keeps_platform_id_and_uses_canonical_model_id() -> None:
    client = FakeClient()
    snapshot = SleeperImporter(client=client).import_league("L1", external_user_id="u1")
    pick = snapshot.metadata["live_draft_picks"][0]
    assert pick["platform_player_id"] == "p2"
    assert pick["canonical_player_id"] == "g2"
    assert pick["player_id"] == "g2"
    assert pick["player_name"] == "Player Two"
    assert pick["position"] == "WR"
