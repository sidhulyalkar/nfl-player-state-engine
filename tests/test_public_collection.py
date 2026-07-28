from __future__ import annotations

import socket

import pytest

from player_state_engine.intelligence.collectors.access import (
    AccessBoundaryError,
    validate_public_url,
)
from player_state_engine.intelligence.collectors.page_extract import (
    detect_access_wall,
    extract_public_page,
)


def test_url_guard_blocks_private_and_credentials() -> None:
    with pytest.raises(AccessBoundaryError):
        validate_public_url("http://127.0.0.1/admin", resolve_dns=False)
    with pytest.raises(AccessBoundaryError):
        validate_public_url("https://user:secret@example.com/page", resolve_dns=False)
    with pytest.raises(AccessBoundaryError):
        validate_public_url("file:///etc/passwd", resolve_dns=False)


def test_url_guard_allows_public_name_without_dns_resolution() -> None:
    assert validate_public_url("https://example.com/player", resolve_dns=False).startswith(
        "https://"
    )


def test_url_guard_rejects_dns_to_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("10.0.0.8", 0))]
    )
    with pytest.raises(AccessBoundaryError):
        validate_public_url("https://example.test/player")


def test_access_wall_detection_fails_closed() -> None:
    html = "<html><body><form action='/login'><input type='password'></form></body></html>"
    with pytest.raises(AccessBoundaryError):
        detect_access_wall(html)


def test_extract_public_article_with_timestamp() -> None:
    html = """
    <html><head>
      <title>Camp update</title>
      <link rel="canonical" href="/news/player-camp">
      <meta property="article:published_time" content="2025-08-12T15:30:00Z">
      <meta name="description" content="A public training update.">
    </head><body><nav>Log in</nav><article>Player discussed route work and recovery.</article></body></html>
    """
    result = extract_public_page(html, "https://example.com/original")
    assert result.canonical_url == "https://example.com/news/player-camp"
    assert result.authored_at_utc is not None
    assert "route work" in result.text
    assert result.metadata["text_sha256"]
