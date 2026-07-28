from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig


def score_fantasy_stats(frame: pd.DataFrame, config: LeagueConfig) -> pd.Series:
    """Score row-level stat outcomes under the league's actual scoring rules."""
    total = pd.Series(0.0, index=frame.index, dtype=float)
    for statistic, weight in config.scoring_weights.items():
        if statistic in frame:
            total = total + pd.to_numeric(frame[statistic], errors="coerce").fillna(0.0) * float(
                weight
            )
    if config.tight_end_premium and "position" in frame and "receptions" in frame:
        receptions = pd.to_numeric(frame["receptions"], errors="coerce").fillna(0.0)
        total = (
            total + frame["position"].astype(str).eq("TE") * receptions * config.tight_end_premium
        )
    return total


def score_quantile_components(
    frame: pd.DataFrame,
    config: LeagueConfig,
    quantiles: tuple[int, ...] = (10, 50, 90),
) -> pd.DataFrame:
    """Approximate fantasy quantiles from stat quantiles.

    This is convenient for tables but is not distributionally exact because
    quantiles are not additive. Prefer scoring correlated simulation draws when
    the component-level simulator is available.
    """
    out = frame.copy()
    for quantile in quantiles:
        component = pd.DataFrame(index=frame.index)
        for statistic in config.scoring_weights:
            column = f"{statistic}_q{quantile}"
            if column in frame:
                component[statistic] = frame[column]
        if "position" in frame:
            component["position"] = frame["position"]
        out[f"league_fantasy_points_q{quantile}"] = score_fantasy_stats(component, config)
    return out
