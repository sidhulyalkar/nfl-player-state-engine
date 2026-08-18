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


def _default_flex_eligibility() -> dict[str, tuple[str, ...]]:
    return {
        "FLEX": ("RB", "WR", "TE"),
        "W/R/T": ("RB", "WR", "TE"),
        "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
        "SUPERFLEX": ("QB", "RB", "WR", "TE"),
        "SF": ("QB", "RB", "WR", "TE"),
        "OP": ("QB", "RB", "WR", "TE"),
        "REC_FLEX": ("WR", "TE"),
        "WR/TE": ("WR", "TE"),
        "RB/WR": ("RB", "WR"),
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
    flex_eligibility: dict[str, tuple[str, ...]] = field(default_factory=_default_flex_eligibility)
    median_scoring: bool = False
    median_game_weight: float = 1.0
    draft_type: str = "snake"
    bench_value_weight: float = 0.20
    replacement_buffer_fraction: float = 0.25

    def __post_init__(self) -> None:
        defaults = _default_scoring(self.scoring)
        defaults.update(self.scoring_weights)
        self.scoring_weights = defaults
        normalized_slots: dict[str, int] = {}
        for slot, count in self.roster_slots.items():
            normalized_slots[str(slot).upper()] = max(0, int(count))
        self.roster_slots = normalized_slots
        normalized_flex: dict[str, tuple[str, ...]] = {}
        for slot, positions in self.flex_eligibility.items():
            normalized_flex[str(slot).upper()] = tuple(str(position).upper() for position in positions)
        self.flex_eligibility = normalized_flex
        self.teams = max(1, int(self.teams))
        self.replacement_buffer = max(0, int(self.replacement_buffer))
        self.risk_preference = min(1.0, max(0.0, float(self.risk_preference)))
        self.median_game_weight = max(0.0, float(self.median_game_weight))
        self.bench_value_weight = min(1.0, max(0.0, float(self.bench_value_weight)))
        self.replacement_buffer_fraction = min(1.0, max(0.0, float(self.replacement_buffer_fraction)))

    @property
    def flex_slots(self) -> dict[str, int]:
        return {
            slot: count
            for slot, count in self.roster_slots.items()
            if slot in self.flex_eligibility and count > 0
        }

    @property
    def direct_starter_slots(self) -> dict[str, int]:
        ignored = set(self.flex_eligibility) | {"BENCH", "IR", "RESERVE", "TAXI"}
        return {
            slot: count
            for slot, count in self.roster_slots.items()
            if slot not in ignored and count > 0
        }

    @property
    def is_multi_qb(self) -> bool:
        if self.roster_slots.get("QB", 0) >= 2:
            return True
        return any(
            count > 0 and "QB" in self.flex_eligibility.get(slot, ())
            for slot, count in self.flex_slots.items()
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> LeagueConfig:
        payload = yaml.safe_load(Path(path).read_text()) or {}
        if "playoff_weeks" in payload:
            payload["playoff_weeks"] = tuple(payload["playoff_weeks"])
        if "flex_eligibility" in payload:
            payload["flex_eligibility"] = {
                str(slot): tuple(positions)
                for slot, positions in (payload["flex_eligibility"] or {}).items()
            }
        return cls(**payload)
