from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class CachedHttpClient:
    def __init__(
        self,
        cache_dir: str | Path,
        user_agent: str = "NFLPlayerStateEngine/0.3 public-research-collector",
        timeout_seconds: float = 20.0,
        min_interval_seconds: float = 1.0,
    ) -> None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - optional dependency boundary
            raise RuntimeError(
                'Install intelligence dependencies with `pip install -e ".[intelligence]"`.'
            ) from exc
        self._httpx = httpx
        self.client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json,text/html,application/rss+xml",
            },
        )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval_seconds = min_interval_seconds
        self._last_request_by_host: dict[str, float] = {}

    def _throttle(self, url: str) -> None:
        host = self._httpx.URL(url).host or "unknown"
        elapsed = time.monotonic() - self._last_request_by_host.get(host, 0.0)
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self._last_request_by_host[host] = time.monotonic()

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self._throttle(url)
        response = self.client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response

    def post(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self._throttle(url)
        response = self.client.post(url, params=params, json=json_body, headers=headers)
        response.raise_for_status()
        return response

    def cache_text(self, namespace: str, key: str, payload: str) -> Path:
        safe_key = "".join(
            character if character.isalnum() or character in "-_" else "_" for character in key
        )
        path = self.cache_dir / namespace / f"{safe_key}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        return path

    def cache_json(self, namespace: str, key: str, payload: Any) -> Path:
        safe_key = "".join(
            character if character.isalnum() or character in "-_" else "_" for character in key
        )
        path = self.cache_dir / namespace / f"{safe_key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        return path
