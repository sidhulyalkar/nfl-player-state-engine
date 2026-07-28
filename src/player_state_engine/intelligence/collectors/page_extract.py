from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from player_state_engine.intelligence.collectors.access import AccessBoundaryError


@dataclass(slots=True)
class ExtractedPublicPage:
    title: str | None
    text: str
    canonical_url: str
    authored_at_utc: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


_STRONG_LOGIN_MARKERS = (
    "input[type='password']",
    "form[action*='login' i]",
    "form[action*='signin' i]",
    "[data-testid*='login' i] form",
)
_STRONG_CHALLENGE_MARKERS = (
    "iframe[src*='captcha' i]",
    "[class*='captcha' i]",
    "[id*='captcha' i]",
    "[data-testid*='challenge' i]",
)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    return parsed


def _json_ld_objects(soup: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for node in soup.select("script[type='application/ld+json']"):
        raw = node.string or node.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and isinstance(candidate.get("@graph"), list):
                candidates.extend(item for item in candidate["@graph"] if isinstance(item, dict))
            if isinstance(candidate, dict):
                objects.append(candidate)
    return objects


def detect_access_wall(html: str, *, visible_text: str | None = None) -> None:
    """Fail closed on login, CAPTCHA, or challenge pages.

    A public page may mention login in navigation, so text-only markers are used
    only when the page contains little substantive content.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            'Install intelligence dependencies with `pip install -e ".[intelligence]"`.'
        ) from exc

    soup = BeautifulSoup(html, "html.parser")
    if any(soup.select_one(selector) is not None for selector in _STRONG_LOGIN_MARKERS):
        raise AccessBoundaryError("Page requires authentication; collection stopped.")
    if any(soup.select_one(selector) is not None for selector in _STRONG_CHALLENGE_MARKERS):
        raise AccessBoundaryError(
            "Page presents an access challenge or CAPTCHA; collection stopped."
        )

    text = " ".join((visible_text or soup.get_text(" ", strip=True)).lower().split())
    title = " ".join((soup.title.get_text(" ", strip=True) if soup.title else "").lower().split())
    challenge_phrases = (
        "verify you are human",
        "unusual traffic",
        "complete the security check",
        "access denied",
        "please log in to continue",
        "sign in to continue",
    )
    if any(phrase in title for phrase in challenge_phrases):
        raise AccessBoundaryError("Page is an access challenge rather than public content.")
    if len(text) < 500 and any(phrase in text for phrase in challenge_phrases):
        raise AccessBoundaryError("Page requires login or an access challenge.")


def extract_public_page(
    html: str, source_url: str, *, visible_text: str | None = None
) -> ExtractedPublicPage:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            'Install intelligence dependencies with `pip install -e ".[intelligence]"`.'
        ) from exc

    detect_access_wall(html, visible_text=visible_text)
    soup = BeautifulSoup(html, "html.parser")

    canonical_node = soup.select_one("link[rel='canonical']")
    canonical = (
        urljoin(source_url, canonical_node.get("href"))
        if canonical_node and canonical_node.get("href")
        else source_url
    )

    title = None
    for selector, attribute in (
        ("meta[property='og:title']", "content"),
        ("meta[name='twitter:title']", "content"),
    ):
        node = soup.select_one(selector)
        if node and node.get(attribute):
            title = str(node.get(attribute)).strip()
            break
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True) or None

    json_ld = _json_ld_objects(soup)
    authored_at = None
    for candidate in json_ld:
        authored_at = _parse_datetime(str(candidate.get("datePublished", "")))
        if authored_at:
            break
    if authored_at is None:
        for selector, attribute in (
            ("meta[property='article:published_time']", "content"),
            ("time[datetime]", "datetime"),
        ):
            node = soup.select_one(selector)
            authored_at = (
                _parse_datetime(str(node.get(attribute))) if node and node.get(attribute) else None
            )
            if authored_at:
                break

    og_description = None
    for selector in ("meta[property='og:description']", "meta[name='description']"):
        node = soup.select_one(selector)
        if node and node.get("content"):
            og_description = " ".join(str(node.get("content")).split())
            break

    for tag in soup(["script", "style", "noscript", "svg", "canvas", "template"]):
        tag.decompose()
    for selector in ("nav", "footer", "aside", "form"):
        for node in soup.select(selector):
            node.decompose()

    if visible_text:
        body_text = " ".join(visible_text.split())
    else:
        article = soup.select_one("article") or soup.select_one("main") or soup.body or soup
        body_text = " ".join(article.get_text(" ", strip=True).split())
    text_parts = [part for part in (title, og_description, body_text) if part]
    text = " ".join(dict.fromkeys(text_parts))
    if not text:
        raise ValueError("No public text content was extracted from the page.")

    metadata: dict[str, Any] = {
        "canonical_url": canonical,
        "json_ld_types": sorted(
            {str(item.get("@type")) for item in json_ld if item.get("@type") is not None}
        ),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    return ExtractedPublicPage(
        title=title,
        text=text,
        canonical_url=canonical,
        authored_at_utc=authored_at,
        metadata=metadata,
    )
