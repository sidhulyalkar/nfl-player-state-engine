from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class YahooOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


class YahooFantasyImporter:
    """Yahoo integration boundary.

    Yahoo Fantasy requires approved API access and OAuth. This adapter intentionally
    contains no credential scraping. The frontend should initiate OAuth, store refresh
    tokens server-side, then normalize league/team/player resources into LeagueSnapshot.
    """

    platform = "yahoo"
    api_base = "https://fantasysports.yahooapis.com/fantasy/v2"
    authorization_url = "https://api.login.yahoo.com/oauth2/request_auth"
    token_url = "https://api.login.yahoo.com/oauth2/get_token"

    @staticmethod
    def league_resource_url(league_key: str) -> str:
        return f"{YahooFantasyImporter.api_base}/league/{league_key};out=settings,standings,teams,players"

    def import_league(self, league_id: str, **kwargs: object):
        raise RuntimeError(
            "Yahoo import requires an approved Yahoo Fantasy application and OAuth token. "
            "See docs/product/platform_integrations.md."
        )
