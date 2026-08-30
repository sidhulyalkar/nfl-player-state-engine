from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import score_fantasy_stats
from player_state_engine.features.weekly import canonicalize_player_stats

LEAGUE_SCORE_TARGET = "league_fantasy_points"

# nflverse publishes these fantasy scoring families as separate play-type columns. They are
# aggregated before scoring so the direct target matches the scoring contract rather than a
# convenience subset of player box-score fields.
_SPLIT_SCORING_COLUMNS: dict[str, tuple[str, ...]] = {
    "fumbles_lost": (
        "sack_fumbles_lost",
        "rushing_fumbles_lost",
        "receiving_fumbles_lost",
    ),
    "two_point_conversions": (
        "passing_2pt_conversions",
        "rushing_2pt_conversions",
        "receiving_2pt_conversions",
    ),
}
_STANDARD_SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "passing_yards": ("passing_yards",),
    "passing_tds": ("passing_tds",),
    "interceptions": ("interceptions", "passing_interceptions"),
    "rushing_yards": ("rushing_yards",),
    "rushing_tds": ("rushing_tds",),
    "receptions": ("receptions",),
    "receiving_yards": ("receiving_yards",),
    "receiving_tds": ("receiving_tds",),
    "special_teams_tds": ("special_teams_tds",),
}

# nflfastR::calculate_stats() currently defines fantasy_points_ppr as the ordinary PPR offense
# formula plus six points per individual special-teams touchdown. LeagueConfig intentionally does
# not assume that every fantasy platform awards those points to the offensive player. We therefore
# keep the league target and the upstream reference as separate scoring contracts.
_NFLVERSE_PPR_REFERENCE_EXTRA_WEIGHTS = {"special_teams_tds": 6.0}


@dataclass(frozen=True, slots=True)
class LeagueScoreTargetDiagnostics:
    target: str
    rows: int
    zero_score_rows: int
    scoring: str
    tight_end_premium: float
    nonzero_scoring_weights: dict[str, float]
    source_columns: dict[str, tuple[str, ...]]
    ppr_reference_contract: str | None
    ppr_reference_rows: int
    ppr_reference_mae: float | None
    ppr_reference_max_abs_error: float | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _required_source_columns(raw: pd.DataFrame, config: LeagueConfig) -> dict[str, tuple[str, ...]]:
    resolved: dict[str, tuple[str, ...]] = {}
    missing: list[str] = []
    for statistic, weight in config.scoring_weights.items():
        if abs(float(weight)) <= 1e-12:
            continue
        if statistic in _SPLIT_SCORING_COLUMNS:
            columns = _SPLIT_SCORING_COLUMNS[statistic]
            absent = [column for column in columns if column not in raw.columns]
            if absent:
                missing.append(f"{statistic}:{','.join(absent)}")
            else:
                resolved[statistic] = columns
            continue
        aliases = _STANDARD_SOURCE_ALIASES.get(statistic, (statistic,))
        source = next((column for column in aliases if column in raw.columns), None)
        if source is None:
            missing.append(f"{statistic}:{'/'.join(aliases)}")
        else:
            resolved[statistic] = (source,)
    if config.tight_end_premium and "receptions" not in raw.columns:
        missing.append("tight_end_premium:receptions")
    if missing:
        raise ValueError(
            "League scoring target cannot be constructed from the source schema; missing "
            + "; ".join(missing)
        )
    return resolved


def _attach_scoring_fields(
    raw: pd.DataFrame,
    source_columns: dict[str, tuple[str, ...]],
) -> pd.DataFrame:
    data = canonicalize_player_stats(raw)
    for statistic, columns in source_columns.items():
        if statistic not in _SPLIT_SCORING_COLUMNS:
            continue
        values = [pd.to_numeric(raw[column], errors="coerce").fillna(0.0) for column in columns]
        total = values[0].copy()
        for value in values[1:]:
            total = total + value
        data[statistic] = total.astype(float).to_numpy()
    return data


def _canonical_ppr_reference(
    canonical: pd.DataFrame,
    config: LeagueConfig,
) -> tuple[pd.Series | None, str | None]:
    canonical_ppr = (
        config.scoring.lower() == "ppr"
        and float(config.tight_end_premium) == 0.0
        and config.scoring_weights == LeagueConfig(scoring="ppr").scoring_weights
    )
    if not canonical_ppr:
        return None, None
    if "special_teams_tds" not in canonical.columns:
        raise ValueError(
            "Canonical nflverse PPR reconciliation requires the special_teams_tds source field"
        )
    reference_config = LeagueConfig(
        scoring="ppr",
        scoring_weights=dict(_NFLVERSE_PPR_REFERENCE_EXTRA_WEIGHTS),
    )
    return (
        score_fantasy_stats(canonical, reference_config),
        "nflverse_calculate_stats_ppr_including_special_teams_tds",
    )


def build_preseason_league_scored_dataset(
    preseason_dataset: pd.DataFrame,
    player_stats: pd.DataFrame,
    config: LeagueConfig,
    *,
    target: str = LEAGUE_SCORE_TARGET,
) -> tuple[pd.DataFrame, LeagueScoreTargetDiagnostics]:
    """Attach a direct, leakage-safe season fantasy-score target for one league contract.

    Historical football outcomes are scored *before* the season target is modeled. This avoids
    adding marginal component quantiles and therefore preserves the actual joint scoring outcome
    in the training target. Opening-roster rows with no regular-season box-score row remain zero.

    The target is an outcome only. It is joined after the season-start feature universe has been
    created, so same-season scoring never enters preseason predictors.
    """

    if preseason_dataset.empty:
        raise ValueError("Preseason dataset must be non-empty")
    raw = player_stats.copy()
    if "season_type" in raw.columns:
        raw = raw.loc[raw["season_type"].astype(str).str.upper().eq("REG")].copy()
    if raw.empty:
        raise ValueError("No regular-season player-stat rows are available")

    source_columns = _required_source_columns(raw, config)
    canonical = _attach_scoring_fields(raw, source_columns)
    canonical[target] = score_fantasy_stats(canonical, config)
    season_scores = (
        canonical.groupby(["season", "player_id"], as_index=False)[target]
        .sum()
        .astype({"season": int})
    )

    out = preseason_dataset.drop(columns=[target], errors="ignore").merge(
        season_scores,
        on=["season", "player_id"],
        how="left",
        validate="one_to_one",
    )
    out[target] = pd.to_numeric(out[target], errors="coerce").fillna(0.0)

    # Give the prior-season baseline its natural direct-score comparator. The model feature family
    # remains the already-frozen preseason family of prior football components and roster state.
    for lag in (1, 2):
        prior = out[["season", "player_id", target]].copy()
        prior["season"] = prior["season"] + lag
        prior = prior.rename(columns={target: f"prior{lag}_{target}"})
        out = out.merge(prior, on=["season", "player_id"], how="left", validate="one_to_one")

    reference_rows = 0
    reference_mae: float | None = None
    reference_max: float | None = None
    reference_score, reference_contract = _canonical_ppr_reference(canonical, config)
    if reference_score is not None and "fantasy_points_ppr" in canonical.columns:
        published = pd.to_numeric(canonical["fantasy_points_ppr"], errors="coerce")
        valid = reference_score.notna() & published.notna()
        reference_rows = int(valid.sum())
        if reference_rows:
            error = (reference_score.loc[valid] - published.loc[valid]).abs()
            reference_mae = float(error.mean())
            reference_max = float(error.max())

    diagnostics = LeagueScoreTargetDiagnostics(
        target=target,
        rows=int(len(out)),
        zero_score_rows=int(out[target].eq(0.0).sum()),
        scoring=config.scoring,
        tight_end_premium=float(config.tight_end_premium),
        nonzero_scoring_weights={
            statistic: float(weight)
            for statistic, weight in config.scoring_weights.items()
            if abs(float(weight)) > 1e-12
        },
        source_columns={key: tuple(value) for key, value in source_columns.items()},
        ppr_reference_contract=reference_contract,
        ppr_reference_rows=reference_rows,
        ppr_reference_mae=reference_mae,
        ppr_reference_max_abs_error=reference_max,
    )
    return out, diagnostics
