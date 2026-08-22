from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import prepare_league_scoring_quantiles


@dataclass(frozen=True, slots=True)
class LeagueReadinessReport:
    score: float
    ready: bool
    flags: tuple[str, ...]
    required_positions: tuple[str, ...]
    missing_positions: tuple[str, ...]
    projection_rows: int
    unique_player_coverage: float
    market_adp_coverage: float
    exact_scoring_coverage: float
    valuation_coverage: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def required_projection_positions(config: LeagueConfig) -> tuple[str, ...]:
    positions = set(config.direct_starter_slots)
    for slot, count in config.flex_slots.items():
        if count > 0:
            positions.update(config.flex_eligibility.get(slot, ()))
    return tuple(sorted(position for position in positions if position not in {"BENCH", "IR"}))


def assess_league_readiness(projections: pd.DataFrame, config: LeagueConfig) -> LeagueReadinessReport:
    """Audit whether a projection pool is safe to use for league decisions."""

    flags: list[str] = []
    rows = len(projections)
    required = required_projection_positions(config)

    if "position" in projections:
        present = set(projections["position"].astype(str).str.upper())
    else:
        present = set()
        flags.append("MISSING_POSITION_COLUMN")
    missing_positions = tuple(position for position in required if position not in present)
    if missing_positions:
        flags.append("MISSING_REQUIRED_POSITIONS")

    if "player_id" not in projections:
        unique_coverage = 0.0
        flags.append("MISSING_PLAYER_ID")
    elif rows == 0:
        unique_coverage = 0.0
    else:
        ids = projections["player_id"].astype(str)
        unique_coverage = float(ids.nunique(dropna=False) / rows)
        if ids.duplicated().any():
            flags.append("DUPLICATE_PLAYER_IDS")

    market_column = (
        "market_adp"
        if "market_adp" in projections
        else "market_cost"
        if "market_cost" in projections
        else None
    )
    if market_column is None or rows == 0:
        market_coverage = 0.0
        flags.append("MISSING_MARKET_DATA")
    else:
        market_coverage = float(
            pd.to_numeric(projections[market_column], errors="coerce").notna().mean()
        )
        if market_coverage < 0.70:
            flags.append("LOW_MARKET_COVERAGE")

    if rows == 0:
        exact_scoring_coverage = 0.0
        valuation_coverage = 0.0
    else:
        try:
            scored = prepare_league_scoring_quantiles(projections, config)
            exact_scoring_coverage = float(
                (~scored["league_scoring_fallback"].astype(bool)).mean()
                if "league_scoring_fallback" in scored
                else scored["league_scoring_source"].ne("generic_points_fallback").mean()
            )
            valuation_coverage = float(
                pd.to_numeric(scored["valuation_points_q50"], errors="coerce").notna().mean()
            )
        except ValueError:
            exact_scoring_coverage = 0.0
            valuation_coverage = 0.0
            flags.append("UNSCORABLE_PROJECTIONS")
    if exact_scoring_coverage < 0.80:
        flags.append("GENERIC_SCORING_FALLBACK")
    if valuation_coverage < 0.98:
        flags.append("INCOMPLETE_VALUATION_COVERAGE")

    position_coverage = 1.0 if not required else 1.0 - len(missing_positions) / len(required)
    score = 100.0 * (
        0.30 * float(np.clip(position_coverage, 0.0, 1.0))
        + 0.15 * float(np.clip(unique_coverage, 0.0, 1.0))
        + 0.20 * float(np.clip(market_coverage, 0.0, 1.0))
        + 0.20 * float(np.clip(exact_scoring_coverage, 0.0, 1.0))
        + 0.15 * float(np.clip(valuation_coverage, 0.0, 1.0))
    )
    hard_flags = {
        "MISSING_REQUIRED_POSITIONS",
        "MISSING_PLAYER_ID",
        "DUPLICATE_PLAYER_IDS",
        "UNSCORABLE_PROJECTIONS",
        "INCOMPLETE_VALUATION_COVERAGE",
    }
    ready = not bool(hard_flags.intersection(flags)) and score >= 65.0
    return LeagueReadinessReport(
        score=float(np.clip(score, 0.0, 100.0)),
        ready=bool(ready),
        flags=tuple(dict.fromkeys(flags)),
        required_positions=required,
        missing_positions=missing_positions,
        projection_rows=int(rows),
        unique_player_coverage=float(unique_coverage),
        market_adp_coverage=float(market_coverage),
        exact_scoring_coverage=float(exact_scoring_coverage),
        valuation_coverage=float(valuation_coverage),
    )
