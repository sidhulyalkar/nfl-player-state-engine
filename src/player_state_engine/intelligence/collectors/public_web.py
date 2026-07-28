from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from player_state_engine.intelligence.collectors.access import (
    AccessBoundaryError,
    validate_public_url,
)
from player_state_engine.intelligence.collectors.http import CachedHttpClient
from player_state_engine.intelligence.collectors.page_extract import extract_public_page
from player_state_engine.intelligence.schemas import PlayerSource, PublicDocument


def document_cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


class PublicWebCollector:
    platform = "public_web"

    def __init__(
        self, cache_dir: str = "data/external/intelligence/cache", max_bytes: int = 2_000_000
    ) -> None:
        self.http = CachedHttpClient(cache_dir)
        self.max_bytes = max_bytes

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(validate_public_url(url))
        robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
        try:
            response = self.http.get(robots_url)
            validate_public_url(str(response.url))
        except Exception:  # noqa: BLE001
            return False
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser.can_fetch("NFLPlayerStateEngine/0.3", url)

    def collect(self, source: PlayerSource, limit: int = 50):
        del limit
        if not source.url:
            raise ValueError("public_web sources require a URL.")
        validate_public_url(source.url)
        if not self._robots_allowed(source.url):
            raise AccessBoundaryError(f"robots.txt does not allow collection: {source.url}")
        response = self.http.get(source.url)
        final_url = str(response.url)
        validate_public_url(final_url)
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            raise ValueError(f"Expected HTML, received {content_type!r}.")
        if len(response.content) > self.max_bytes:
            raise ValueError("Page exceeds configured maximum response size.")
        self.http.cache_text("public_web", document_cache_key(final_url), response.text)
        extracted = extract_public_page(response.text, final_url)
        document_id = hashlib.sha256(
            f"{source.player_id}|{extracted.canonical_url}|{extracted.text}".encode()
        ).hexdigest()[:24]
        yield PublicDocument(
            document_id=document_id,
            player_id=source.player_id,
            player_name=source.player_name,
            platform="public_web",
            source_url=extracted.canonical_url,
            text=extracted.text,
            title=extracted.title,
            authored_at_utc=extracted.authored_at_utc,
            collected_at_utc=datetime.now(UTC),
            metadata={
                **extracted.metadata,
                "collector": "public_web_v2",
                "public_access_only": True,
                "rendered": False,
            },
        )
