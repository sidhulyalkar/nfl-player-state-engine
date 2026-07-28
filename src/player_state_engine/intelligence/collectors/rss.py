from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from player_state_engine.intelligence.schemas import PlayerSource, PublicDocument


class RSSCollector:
    platform = "rss"

    def collect(self, source: PlayerSource, limit: int = 50):
        if not source.url:
            raise ValueError("rss sources require a feed URL.")
        try:
            import feedparser
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                'Install intelligence dependencies with `pip install -e ".[intelligence]"`.'
            ) from exc
        feed = feedparser.parse(source.url)
        for entry in feed.entries[:limit]:
            text = " ".join(
                str(
                    entry.get("summary") or entry.get("description") or entry.get("title") or ""
                ).split()
            )
            if not text:
                continue
            url = str(entry.get("link") or source.url)
            document_id = hashlib.sha256(f"{source.player_id}|{url}|{text}".encode()).hexdigest()[
                :24
            ]
            authored = None
            parsed = entry.get("published_parsed") or entry.get("updated_parsed")
            if parsed:
                authored = datetime(*parsed[:6], tzinfo=UTC)
            yield PublicDocument(
                document_id=document_id,
                player_id=source.player_id,
                player_name=source.player_name,
                platform="rss",
                source_url=url,
                title=entry.get("title"),
                text=text,
                authored_at_utc=authored,
                collected_at_utc=datetime.now(UTC),
            )
