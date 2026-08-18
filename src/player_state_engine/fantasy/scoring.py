from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig

# These are the minimum components required before a generic season-points projection is
# replaced by a component-level league rescore. Optional statistics (two-point conversions,
# bonuses, etc.) are still scored when present, but their absence must not silently turn a
# partial projection into an "exact" custom-league projection.
_PRIMARY_STATS_BY_POSITION: dict[str, tuple[str, ...]] = {
    "QB": ("passing_yards", "passing_tds", "interceptions", "rushing_yards", "rushing_tds"),
    "RB": ("rushing_yards", "rushing_tds", "receptions", "receiving_yards", "receiving_tds"),
    "WR": ("receptions", "receiving_yards", "receiving_tds"),
    "TE": ("receptions", "receiving_yards", "receiving_tds"),
}


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
            total
            + frame["position"].astype(str).str.upper().eq("TE")
            * receptions
            * config.tight_end_premium
        )
    return total


def score_quantile_components(
    frame: pd.DataFrame,
    config: LeagueConfig,
    quantiles: tuple[int, ...] = (10, 50, 90),
) -> pd.DataFrame:
    """Approximate fantasy quantiles from stat quantiles.

    Quantiles are not additive, so these columns are a deterministic approximation. When
    correlated stat draws are available, score those draws first with ``score_simulation_draws``
    and aggregate the scored distribution instead.
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


def score_simulation_draws(frame: pd.DataFrame, config: LeagueConfig) -> pd.DataFrame:
    """Score correlated football-stat simulation draws under exact league scoring.

    Each row is treated as one already-correlated football outcome. This is the preferred
    scoring boundary because touchdowns, yards, catches, availability and opportunity remain
    coupled before fantasy points are calculated.
    """
    out = frame.copy()
    out["league_fantasy_points"] = score_fantasy_stats(out, config)
    return out


def aggregate_scored_draws(
    draws: pd.DataFrame,
    *,
    group_columns: Sequence[str] = ("player_id",),
    value_column: str = "league_fantasy_points",
    quantiles: Iterable[float] = (0.10, 0.50, 0.90),
    prefix: str = "valuation_points",
) -> pd.DataFrame:
    """Aggregate scored Monte Carlo draws into player-level fantasy quantiles."""
    groups = [column for column in group_columns if column in draws]
    if not groups:
        raise ValueError("At least one group column must be present in scored draws.")
    if value_column not in draws:
        raise ValueError(f"Missing scored draw column: {value_column}")
    values = pd.to_numeric(draws[value_column], errors="coerce")
    work = draws.loc[values.notna(), groups].copy()
    work[value_column] = values.loc[values.notna()].astype(float)
    pieces: list[pd.DataFrame] = []
    for quantile in quantiles:
        label = int(round(float(quantile) * 100))
        piece = (
            work.groupby(groups, dropna=False)[value_column]
            .quantile(float(quantile))
            .rename(f"{prefix}_q{label}")
            .reset_index()
        )
        pieces.append(piece)
    result = pieces[0]
    for piece in pieces[1:]:
        result = result.merge(piece, on=groups, how="outer", validate="one_to_one")
    result["league_scoring_source"] = "correlated_draw_rescore"
    result["league_scoring_coverage"] = 1.0
    return result


def _required_component_columns(position: str, quantiles: tuple[int, ...]) -> tuple[str, ...]:
    statistics = _PRIMARY_STATS_BY_POSITION.get(position.upper(), ())
    return tuple(f"{statistic}_q{quantile}" for statistic in statistics for quantile in quantiles)


def _component_coverage(frame: pd.DataFrame, quantiles: tuple[int, ...]) -> pd.Series:
    positions = (
        frame["position"].astype(str).str.upper()
        if "position" in frame
        else pd.Series("", index=frame.index, dtype=str)
    )
    coverage = pd.Series(0.0, index=frame.index, dtype=float)
    for position, indexes in positions.groupby(positions).groups.items():
        required = _required_component_columns(str(position), quantiles)
        if not required:
            continue
        available = [column for column in required if column in frame]
        if not available:
            continue
        nonmissing = frame.loc[indexes, available].notna().sum(axis=1)
        coverage.loc[indexes] = nonmissing / float(len(required))
    return coverage.clip(0.0, 1.0)


def prepare_league_scoring_quantiles(
    frame: pd.DataFrame,
    config: LeagueConfig,
    *,
    quantiles: tuple[int, ...] = (10, 50, 90),
    fallback_prefix: str = "season_points",
) -> pd.DataFrame:
    """Create canonical valuation quantiles under the requested league rules.

    Priority order is deliberately explicit:

    1. Already-scored ``league_season_points_q*`` columns from a correlated simulator.
    2. Complete position-relevant component quantiles rescored with league weights.
    3. Generic ``season_points_q*`` fallback, clearly marked as such.

    The third path preserves backwards compatibility but never masquerades as scoring-exact.
    ``league_scoring_coverage`` makes missing component support observable in the API and
    validation reports.
    """
    out = frame.copy()
    if out.empty:
        for quantile in quantiles:
            out[f"valuation_points_q{quantile}"] = pd.Series(dtype=float)
        out["league_scoring_source"] = pd.Series(dtype=str)
        out["league_scoring_coverage"] = pd.Series(dtype=float)
        return out

    coverage = _component_coverage(out, quantiles)
    component_scored = score_quantile_components(out, config, quantiles=quantiles)
    provided_columns = [f"league_season_points_q{quantile}" for quantile in quantiles]
    provided_complete = pd.Series(True, index=out.index, dtype=bool)
    for column in provided_columns:
        if column not in out:
            provided_complete[:] = False
            break
        provided_complete &= pd.to_numeric(out[column], errors="coerce").notna()

    component_complete = coverage.ge(1.0 - 1e-12)
    fallback_complete = pd.Series(True, index=out.index, dtype=bool)
    for quantile in quantiles:
        fallback_column = f"{fallback_prefix}_q{quantile}"
        if fallback_column not in out:
            fallback_complete[:] = False
            continue
        fallback_complete &= pd.to_numeric(out[fallback_column], errors="coerce").notna()

    if not bool((provided_complete | component_complete | fallback_complete).all()):
        missing_rows = int((~(provided_complete | component_complete | fallback_complete)).sum())
        raise ValueError(
            f"Unable to construct league valuation quantiles for {missing_rows} rows; "
            "provide correlated league points, complete stat quantiles, or generic season points."
        )

    for quantile in quantiles:
        target = pd.Series(np.nan, index=out.index, dtype=float)
        provided = f"league_season_points_q{quantile}"
        component = f"league_fantasy_points_q{quantile}"
        fallback = f"{fallback_prefix}_q{quantile}"
        if provided in out:
            target.loc[provided_complete] = pd.to_numeric(
                out.loc[provided_complete, provided], errors="coerce"
            )
        target.loc[~provided_complete & component_complete] = pd.to_numeric(
            component_scored.loc[~provided_complete & component_complete, component],
            errors="coerce",
        )
        fallback_mask = ~(provided_complete | component_complete)
        if fallback in out:
            target.loc[fallback_mask] = pd.to_numeric(out.loc[fallback_mask, fallback], errors="coerce")
        out[f"valuation_points_q{quantile}"] = target.astype(float)

    out["league_scoring_source"] = np.select(
        [provided_complete, component_complete],
        ["correlated_or_provided_league_quantiles", "component_quantile_rescore"],
        default="generic_points_fallback",
    )
    out["league_scoring_coverage"] = np.where(provided_complete, 1.0, coverage).astype(float)
    out["league_scoring_fallback"] = out["league_scoring_source"].eq("generic_points_fallback")
    return out
