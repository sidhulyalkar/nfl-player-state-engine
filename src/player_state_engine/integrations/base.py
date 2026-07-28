from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from player_state_engine.product.schemas import LeagueSnapshot


class JsonClient(Protocol):
    def get_json(self, url: str) -> Any: ...


class LeagueImporter(ABC):
    platform: str

    @abstractmethod
    def import_league(self, league_id: str, **kwargs: object) -> LeagueSnapshot:
        raise NotImplementedError
