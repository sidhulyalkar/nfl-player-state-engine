from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _default_scoring(scoring: str) -> dict[str, float]:
    reception = {"standard": 0.0, "half_ppr": 0.5, "ppr": 1.0}.get(scoring.lower(), 1.0)
    return {
        "passing_yards": 0.04,
        "passing_tds": 4.0,
        "interceptions": -2.0,
        "rushing_yards": 0.10,
        "rushing_tds": 6.0,
        "receptions": reception,
        "receiving_yards": 0.10,
        "receiving_tds": 6.0,
        "fumbles_lost": -2.0,
        "two_point_conversions": 2.0,
    }


@dataclass(slots=True)
class LeagueConfig:
    teams: int = 12
    scoring: str = "ppr"
    roster_slots: dict[str, int] = field(
        default_factory=lambda: {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6}
    )
    replacement_buffer: int = 1
    playoff_weeks: tuple[int, ...] = (15, 16, 17)
    risk_preference: float = 0.5
    faab_budget: float = 100.0
    tight_end_premium: float = 0.0
    scoring_weights: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        defaults = _default_scoring(self.scoring)
        defaults.update(self.scoring_weights)
        self.scoring_weights = defaults

    @classmethod
    def from_yaml(cls, path: str | Path) -> LeagueConfig:
        payload = yaml.safe_load(Path(path).read_text()) or {}
        if "playoff_weeks" in payload:
            payload["playoff_weeks"] = tuple(payload["playoff_weeks"])
        return cls(**payload)
