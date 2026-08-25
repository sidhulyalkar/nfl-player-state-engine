from __future__ import annotations

from typing import Any

from player_state_engine.integrations.sleeper_drafts import SleeperDraftClient


class FakeJsonClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.urls.append(url)
        if url.endswith("/user/sid"):
            return {"user_id": "u1", "username": "sid"}
        if url.endswith("/user/u1/drafts/nfl/2025"):
            return [{"draft_id": "d1", "status": "complete"}]
        if url.endswith("/draft/d1/picks"):
            return [{"draft_id": "d1", "pick_no": 1, "player_id": "p1"}]
        if url.endswith("/draft/d1/traded_picks"):
            return []
        if url.endswith("/draft/d1"):
            return {"draft_id": "d1", "league_id": "l1", "season": "2025"}
        raise AssertionError(f"Unexpected URL: {url}")


def test_sleeper_draft_client_uses_documented_read_only_endpoints() -> None:
    fake = FakeJsonClient()
    client = SleeperDraftClient(fake)

    user = client.get_user("sid")
    drafts = client.list_user_drafts(str(user["user_id"]), season=2025)
    draft = client.get_draft("d1")
    picks = client.get_draft_picks("d1")
    traded = client.get_draft_traded_picks("d1")

    assert drafts == [{"draft_id": "d1", "status": "complete"}]
    assert draft["draft_id"] == "d1"
    assert picks[0]["pick_no"] == 1
    assert traded == []
    assert fake.urls == [
        "https://api.sleeper.app/v1/user/sid",
        "https://api.sleeper.app/v1/user/u1/drafts/nfl/2025",
        "https://api.sleeper.app/v1/draft/d1",
        "https://api.sleeper.app/v1/draft/d1/picks",
        "https://api.sleeper.app/v1/draft/d1/traded_picks",
    ]
