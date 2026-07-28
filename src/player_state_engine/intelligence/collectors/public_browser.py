from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from player_state_engine.intelligence.collectors.access import (
    AccessBoundaryError,
    PublicHostGuard,
    validate_public_url,
)
from player_state_engine.intelligence.collectors.http import CachedHttpClient
from player_state_engine.intelligence.collectors.page_extract import extract_public_page
from player_state_engine.intelligence.collectors.public_web import document_cache_key
from player_state_engine.intelligence.schemas import PlayerSource, PublicDocument


class PublicBrowserCollector:
    """Render genuinely public pages without credentials or access circumvention.

    The collector starts with an empty browser profile, honors robots.txt, blocks
    private-network requests, and stops on login/CAPTCHA/challenge pages. It does
    not click login controls, import cookies, solve challenges, or reverse-engineer
    private platform endpoints.
    """

    platform = "public_browser"

    def __init__(
        self,
        cache_dir: str | Path = "data/external/intelligence/cache",
        max_bytes: int = 3_000_000,
        timeout_ms: int = 20_000,
    ) -> None:
        self.http = CachedHttpClient(cache_dir)
        self.max_bytes = max_bytes
        self.timeout_ms = timeout_ms

    def _robots_allowed(self, url: str) -> bool:
        parsed = urlparse(validate_public_url(url))
        robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
        response = self.http.get(robots_url)
        validate_public_url(str(response.url))
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(response.text.splitlines())
        return parser.can_fetch("NFLPlayerStateEngine/0.3", url)

    def collect(self, source: PlayerSource, limit: int = 50):
        del limit
        if not source.url:
            raise ValueError("public_browser sources require a URL.")
        validate_public_url(source.url)
        if not self._robots_allowed(source.url):
            raise AccessBoundaryError(f"robots.txt does not allow collection: {source.url}")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - optional dependency boundary
            raise RuntimeError(
                'Install browser support with `pip install -e ".[browser]"` and run '
                "`playwright install chromium`."
            ) from exc

        guard = PublicHostGuard()
        guard.check(source.url)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="NFLPlayerStateEngine/0.3 public-research-collector",
                storage_state=None,
                service_workers="block",
                java_script_enabled=True,
            )
            page = context.new_page()

            def route_request(route):  # type: ignore[no-untyped-def]
                request = route.request
                if request.resource_type in {"image", "media", "font", "websocket"}:
                    route.abort()
                    return
                if not guard.check(request.url):
                    route.abort()
                    return
                route.continue_()

            page.route("**/*", route_request)
            try:
                response = page.goto(
                    source.url, wait_until="domcontentloaded", timeout=self.timeout_ms
                )
                page.wait_for_timeout(1_000)
                final_url = page.url
                validate_public_url(final_url)
                if response is not None and response.status >= 400:
                    raise ValueError(f"Public page returned HTTP {response.status}.")
                html = page.content()
                visible_text = page.locator("body").inner_text(timeout=self.timeout_ms)
            finally:
                context.close()
                browser.close()

        payload_bytes = len(html.encode("utf-8"))
        if payload_bytes > self.max_bytes:
            raise ValueError("Rendered page exceeds configured maximum response size.")
        self.http.cache_text("public_browser", document_cache_key(final_url), html)
        extracted = extract_public_page(html, final_url, visible_text=visible_text)
        document_id = hashlib.sha256(
            f"{source.player_id}|{extracted.canonical_url}|{extracted.text}".encode()
        ).hexdigest()[:24]
        yield PublicDocument(
            document_id=document_id,
            player_id=source.player_id,
            player_name=source.player_name,
            platform="public_browser",
            source_url=extracted.canonical_url,
            text=extracted.text,
            title=extracted.title,
            authored_at_utc=extracted.authored_at_utc,
            collected_at_utc=datetime.now(UTC),
            metadata={
                **extracted.metadata,
                "collector": "public_browser_v1",
                "public_access_only": True,
                "rendered": True,
            },
        )
