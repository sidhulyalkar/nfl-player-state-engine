from __future__ import annotations

from typing import Any

from player_state_engine.integrations.base import JsonClient
from player_state_engine.integrations.http import StandardLibraryJsonClient


class SleeperDraftClient:
    """Read-only client for Sleeper historical draft resources."""

    base_url = "https://api.sleeper.app/v1"

    def __init__(self, client: JsonClient | None = None) -> None:
        self.client = client or StandardLibraryJsonClient()

    def source_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _get(self, path: str) -> Any:
        return self.client.get_json(self.source_url(path))

    def get_user(self, username_or_user_id: str) -> dict[str, Any]:
        return dict(self._get(f"user/{username_or_user_id}") or {})

    def list_user_drafts(self, user_id: str, *, season: int) -> list[dict[str, Any]]:
        payload = self._get(f"user/{user_id}/drafts/nfl/{int(season)}") or []
        if not isinstance(payload, list):
            raise ValueError("Sleeper user draft response was not a list")
        return [dict(item) for item in payload if isinstance(item, dict)]

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        return dict(self._get(f"draft/{draft_id}") or {})

    def get_draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
        payload = self._get(f"draft/{draft_id}/picks") or []
        if not isinstance(payload, list):
            raise ValueError("Sleeper draft picks response was not a list")
        return [dict(item) for item in payload if isinstance(item, dict)]

    def get_draft_traded_picks(self, draft_id: str) -> list[dict[str, Any]]:
        payload = self._get(f"draft/{draft_id}/traded_picks") or []
        if not isinstance(payload, list):
            raise ValueError("Sleeper draft traded-picks response was not a list")
        return [dict(item) for item in payload if isinstance(item, dict)]
