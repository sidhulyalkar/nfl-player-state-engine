from __future__ import annotations

from player_state_engine.integrations.base import JsonClient
from player_state_engine.integrations.http import StandardLibraryJsonClient


class FleaflickerImporter:
    platform = "fleaflicker"
    base_url = "https://www.fleaflicker.com/api"

    def __init__(self, client: JsonClient | None = None) -> None:
        self.client = client or StandardLibraryJsonClient()

    def fetch_league_standings(self, league_id: str):
        return self.client.get_json(
            f"{self.base_url}/FetchLeagueStandings?sport=NFL&league_id={league_id}"
        )

    def import_league(self, league_id: str, **kwargs: object):
        raise RuntimeError(
            "Fleaflicker normalization is scaffolded but requires captured fixture samples. "
            "Use its official HTTP API and implement against docs/product/platform_integrations.md."
        )
