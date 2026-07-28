from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class StandardLibraryJsonClient:
    def __init__(
        self, *, timeout_seconds: float = 20.0, user_agent: str = "NFLPlayerStateEngine/0.6"
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def get_json(self, url: str):
        request = Request(
            url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} while requesting {url}") from exc
        except URLError as exc:
            raise RuntimeError(f"Network error while requesting {url}: {exc.reason}") from exc
