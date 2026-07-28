from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

from player_state_engine.intelligence.collectors.http import CachedHttpClient
from player_state_engine.intelligence.schemas import PlayerSource, PublicDocument


class InstagramBusinessDiscoveryCollector:
    """Official Business Discovery connector for public professional accounts only."""

    platform = "instagram"

    def __init__(
        self,
        cache_dir: str = "data/external/intelligence/cache",
        access_token: str | None = None,
        ig_user_id: str | None = None,
        graph_version: str | None = None,
    ) -> None:
        self.token = access_token or os.getenv("META_ACCESS_TOKEN")
        self.ig_user_id = ig_user_id or os.getenv("META_IG_USER_ID")
        if not self.token or not self.ig_user_id:
            raise RuntimeError(
                "META_ACCESS_TOKEN and META_IG_USER_ID are required for Instagram Business Discovery."
            )
        version = graph_version or os.getenv("META_GRAPH_VERSION", "v24.0")
        self.endpoint = f"https://graph.facebook.com/{version}/{self.ig_user_id}"
        self.http = CachedHttpClient(cache_dir)

    def collect(self, source: PlayerSource, limit: int = 25):
        if not source.handle:
            raise ValueError("Instagram sources require a handle.")
        media_limit = max(1, min(limit, 50))
        fields = (
            f"business_discovery.username({source.handle.lstrip('@')})"
            "{username,name,biography,website,followers_count,media_count,"
            f"media.limit({media_limit}){{id,caption,media_type,permalink,timestamp,like_count,comments_count}}}}"
        )
        response = self.http.get(
            self.endpoint,
            params={"fields": fields, "access_token": self.token},
        ).json()
        self.http.cache_json("instagram", source.handle, response)
        discovery = response.get("business_discovery", {})
        for media in discovery.get("media", {}).get("data", []):
            text = str(media.get("caption") or "").strip()
            if not text:
                continue
            media_id = str(media["id"])
            yield PublicDocument(
                document_id=hashlib.sha256(f"instagram|{media_id}".encode()).hexdigest()[:24],
                player_id=source.player_id,
                player_name=source.player_name,
                platform="instagram",
                source_url=str(
                    media.get("permalink") or source.url or "https://www.instagram.com/"
                ),
                text=text,
                author_handle=discovery.get("username") or source.handle,
                authored_at_utc=datetime.fromisoformat(media["timestamp"].replace("Z", "+00:00"))
                if media.get("timestamp")
                else None,
                collected_at_utc=datetime.now(UTC),
                engagement={
                    "like_count": float(media.get("like_count", 0)),
                    "comments_count": float(media.get("comments_count", 0)),
                },
                metadata={
                    "media_type": media.get("media_type"),
                    "api": "instagram-business-discovery",
                },
            )
