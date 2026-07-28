from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

from player_state_engine.intelligence.collectors.http import CachedHttpClient
from player_state_engine.intelligence.schemas import PlayerSource, PublicDocument


class ThreadsApiCollector:
    """Official Threads public profile-post endpoint.

    Availability and permissions depend on Meta app review. No browser automation
    or login-cookie scraping is implemented.
    """

    platform = "threads"
    endpoint = "https://graph.threads.net/v1.0/profile_posts"

    def __init__(
        self, cache_dir: str = "data/external/intelligence/cache", access_token: str | None = None
    ) -> None:
        self.token = access_token or os.getenv("THREADS_ACCESS_TOKEN")
        if not self.token:
            raise RuntimeError(
                "THREADS_ACCESS_TOKEN is required for the official Threads connector."
            )
        self.http = CachedHttpClient(cache_dir)

    def collect(self, source: PlayerSource, limit: int = 50):
        if not source.handle:
            raise ValueError("Threads sources require a handle.")
        response = self.http.get(
            self.endpoint,
            params={
                "username": source.handle.lstrip("@"),
                "fields": "id,text,timestamp,permalink,media_type,username",
                "limit": min(limit, 100),
                "access_token": self.token,
            },
        ).json()
        self.http.cache_json("threads", source.handle, response)
        for post in response.get("data", []):
            text = str(post.get("text") or "").strip()
            if not text:
                continue
            post_id = str(post["id"])
            yield PublicDocument(
                document_id=hashlib.sha256(f"threads|{post_id}".encode()).hexdigest()[:24],
                player_id=source.player_id,
                player_name=source.player_name,
                platform="threads",
                source_url=str(
                    post.get("permalink") or f"https://www.threads.net/@{source.handle}"
                ),
                text=text,
                author_handle=post.get("username") or source.handle,
                authored_at_utc=datetime.fromisoformat(post["timestamp"].replace("Z", "+00:00"))
                if post.get("timestamp")
                else None,
                collected_at_utc=datetime.now(UTC),
                metadata={"media_type": post.get("media_type"), "api": "threads-official"},
            )
