from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.data.io import write_table
from player_state_engine.intelligence.collectors.instagram_api import (
    InstagramBusinessDiscoveryCollector,
)
from player_state_engine.intelligence.collectors.public_browser import PublicBrowserCollector
from player_state_engine.intelligence.collectors.public_web import PublicWebCollector
from player_state_engine.intelligence.collectors.rss import RSSCollector
from player_state_engine.intelligence.collectors.threads_api import ThreadsApiCollector
from player_state_engine.intelligence.collectors.tiktok_api import TikTokResearchCollector
from player_state_engine.intelligence.collectors.x_api import XApiCollector
from player_state_engine.intelligence.io import (
    load_documents_jsonl,
    load_source_registry,
    write_documents_jsonl,
    write_evidence_json,
)
from player_state_engine.intelligence.persona import (
    build_persona_snapshots,
    snapshots_to_feature_frame,
)
from player_state_engine.intelligence.schemas import PublicDocument

LOGGER = logging.getLogger(__name__)


def _collector_for(platform: str, cache_dir: str | Path):
    mapping = {
        "public_web": lambda: PublicWebCollector(str(cache_dir)),
        "public_browser": lambda: PublicBrowserCollector(str(cache_dir)),
        "rss": RSSCollector,
        "x": lambda: XApiCollector(str(cache_dir)),
        "threads": lambda: ThreadsApiCollector(str(cache_dir)),
        "instagram": lambda: InstagramBusinessDiscoveryCollector(str(cache_dir)),
        "tiktok": lambda: TikTokResearchCollector(str(cache_dir)),
    }
    if platform not in mapping:
        raise ValueError(f"No collector is configured for platform {platform!r}.")
    factory = mapping[platform]
    return factory() if callable(factory) else factory


def collect_registry(
    registry_path: str | Path,
    output_path: str | Path,
    cache_dir: str | Path = "data/external/intelligence/cache",
    platforms: Iterable[str] | None = None,
    per_source_limit: int = 50,
    continue_on_error: bool = True,
) -> tuple[Path, list[str]]:
    requested = set(platforms or ())
    sources = load_source_registry(registry_path)
    documents: list[PublicDocument] = []
    errors: list[str] = []
    collectors: dict[str, object] = {}
    for source in sources:
        if not source.enabled or (requested and source.platform not in requested):
            continue
        try:
            if source.platform not in collectors:
                collectors[source.platform] = _collector_for(source.platform, cache_dir)
            collector = collectors[source.platform]
            documents.extend(list(collector.collect(source, limit=per_source_limit)))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            message = f"{source.player_id}:{source.platform}: {exc}"
            errors.append(message)
            LOGGER.warning(message)
            if not continue_on_error:
                raise
    return write_documents_jsonl(documents, output_path), errors


def build_persona_workflow(
    documents_path: str | Path,
    output_path: str | Path,
    evidence_path: str | Path,
    as_of_utc: datetime | None = None,
    lookback_days: int = 120,
) -> dict[str, Path]:
    documents = load_documents_jsonl(documents_path)
    snapshots = build_persona_snapshots(
        documents,
        as_of_utc=as_of_utc or datetime.now(UTC),
        lookback_days=lookback_days,
    )
    frame = snapshots_to_feature_frame(snapshots)
    return {
        "features": write_table(frame, output_path),
        "evidence": write_evidence_json(snapshots, evidence_path),
    }
