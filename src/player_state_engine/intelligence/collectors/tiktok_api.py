from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta

from player_state_engine.intelligence.collectors.http import CachedHttpClient
from player_state_engine.intelligence.schemas import PlayerSource, PublicDocument


class TikTokResearchCollector:
    """Official TikTok Research API connector for approved research projects."""

    platform = "tiktok"
    endpoint = "https://open.tiktokapis.com/v2/research/video/query/"

    def __init__(
        self, cache_dir: str = "data/external/intelligence/cache", access_token: str | None = None
    ) -> None:
        self.token = access_token or os.getenv("TIKTOK_RESEARCH_ACCESS_TOKEN")
        if not self.token:
            raise RuntimeError(
                "TIKTOK_RESEARCH_ACCESS_TOKEN is required and access must be approved by TikTok."
            )
        self.http = CachedHttpClient(cache_dir)
        self.headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def collect(self, source: PlayerSource, limit: int = 50):
        if not source.handle:
            raise ValueError("TikTok sources require a handle.")
        response = self.http.post(
            self.endpoint,
            params={
                "fields": "id,video_description,voice_to_text,create_time,username,like_count,comment_count,share_count,view_count,hashtag_names"
            },
            json_body={
                "query": {
                    "and": [
                        {
                            "operation": "EQ",
                            "field_name": "username",
                            "field_values": [source.handle.lstrip("@")],
                        }
                    ]
                },
                "max_count": min(limit, 100),
                "start_date": (datetime.now(UTC) - timedelta(days=120)).strftime("%Y%m%d"),
                "end_date": datetime.now(UTC).strftime("%Y%m%d"),
                "is_random": False,
            },
            headers=self.headers,
        ).json()
        self.http.cache_json("tiktok", source.handle, response)
        for video in response.get("data", {}).get("videos", []):
            text = " ".join(
                part.strip()
                for part in (
                    str(video.get("video_description") or ""),
                    str(video.get("voice_to_text") or ""),
                )
                if part.strip()
            )
            if not text:
                continue
            video_id = str(video["id"])
            created = video.get("create_time")
            authored = datetime.fromtimestamp(int(created), tz=UTC) if created else None
            yield PublicDocument(
                document_id=hashlib.sha256(f"tiktok|{video_id}".encode()).hexdigest()[:24],
                player_id=source.player_id,
                player_name=source.player_name,
                platform="tiktok",
                source_url=f"https://www.tiktok.com/@{source.handle.lstrip('@')}/video/{video_id}",
                text=text,
                author_handle=video.get("username") or source.handle,
                authored_at_utc=authored,
                collected_at_utc=datetime.now(UTC),
                engagement={
                    key: float(video.get(key, 0))
                    for key in ("like_count", "comment_count", "share_count", "view_count")
                },
                metadata={"hashtags": video.get("hashtag_names", []), "api": "tiktok-research"},
            )
