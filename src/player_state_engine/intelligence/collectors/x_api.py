from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

from player_state_engine.intelligence.collectors.http import CachedHttpClient
from player_state_engine.intelligence.schemas import PlayerSource, PublicDocument


class XApiCollector:
    """Official X API v2 collector for public user posts."""

    platform = "x"
    base_url = "https://api.x.com/2"

    def __init__(
        self, cache_dir: str = "data/external/intelligence/cache", bearer_token: str | None = None
    ) -> None:
        self.token = bearer_token or os.getenv("X_BEARER_TOKEN")
        if not self.token:
            raise RuntimeError("X_BEARER_TOKEN is required for the official X API connector.")
        self.http = CachedHttpClient(cache_dir)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def collect(self, source: PlayerSource, limit: int = 50):
        if not source.handle:
            raise ValueError("X sources require a handle.")
        user_response = self.http.get(
            f"{self.base_url}/users/by/username/{source.handle.lstrip('@')}",
            params={"user.fields": "id,name,username,verified,description"},
            headers=self.headers,
        ).json()
        user = user_response["data"]
        response = self.http.get(
            f"{self.base_url}/users/{user['id']}/tweets",
            params={
                "max_results": max(5, min(limit, 100)),
                "exclude": "retweets,replies",
                "tweet.fields": "created_at,public_metrics,lang,possibly_sensitive",
            },
            headers=self.headers,
        ).json()
        self.http.cache_json("x", source.handle, response)
        for post in response.get("data", []):
            text = post.get("text", "").strip()
            if not text or post.get("possibly_sensitive"):
                continue
            post_id = str(post["id"])
            url = f"https://x.com/{user['username']}/status/{post_id}"
            yield PublicDocument(
                document_id=hashlib.sha256(f"x|{post_id}".encode()).hexdigest()[:24],
                player_id=source.player_id,
                player_name=source.player_name,
                platform="x",
                source_url=url,
                text=text,
                author_handle=user["username"],
                authored_at_utc=datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
                if post.get("created_at")
                else None,
                collected_at_utc=datetime.now(UTC),
                engagement={
                    key: float(value) for key, value in post.get("public_metrics", {}).items()
                },
                metadata={"api": "x-v2"},
            )
