from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from player_state_engine.intelligence.schemas import PlayerSource, PublicDocument


class Collector(Protocol):
    platform: str

    def collect(self, source: PlayerSource, limit: int = 50) -> Iterable[PublicDocument]: ...
