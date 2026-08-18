from __future__ import annotations

from typing import Any


def create_app(**kwargs: Any):
    """Create the full product API, including operational Draft War Room routes."""
    from player_state_engine.api.operational import create_app as create_operational_app

    return create_operational_app(**kwargs)


__all__ = ["create_app"]
