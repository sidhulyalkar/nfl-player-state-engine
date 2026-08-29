from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import (
    prepare_league_scoring_quantiles,
    required_scoring_statistics,
)


def _qb_components(*, include_minor: bool) -> pd.DataFrame:
    row: dict[str, object] = {
        "player_id": "QB1",
        "player_name": "Quarterback One",
        "position": "QB",
        "season_points_q10": 200.0,
        "season_points_q50": 260.0,
        "season_points_q90": 320.0,
    }
    values = {
        "passing_yards": (3000.0, 4000.0, 4800.0),
        "passing_tds": (18.0, 28.0, 38.0),
        "interceptions": (6.0, 10.0, 16.0),
        "rushing_yards": (100.0, 250.0, 500.0),
        "rushing_tds": (1.0, 3.0, 6.0),
    }
    if include_minor:
        values["fumbles_lost"] = (0.0, 1.0, 3.0)
        values["two_point_conversions"] = (0.0, 1.0, 2.0)
    for statistic, quantile_values in values.items():
        for quantile, value in zip((10, 50, 90), quantile_values, strict=True):
            row[f"{statistic}_q{quantile}"] = value
    return pd.DataFrame([row])


def test_standard_ppr_exact_contract_includes_fumbles_and_two_point_conversions() -> None:
    config = LeagueConfig(scoring="ppr")

    required = set(required_scoring_statistics("QB", config))

    assert "fumbles_lost" in required
    assert "two_point_conversions" in required
    assert {"passing_yards", "passing_tds", "interceptions"}.issubset(required)


def test_missing_nonzero_minor_components_forces_visible_generic_fallback() -> None:
    config = LeagueConfig(scoring="ppr")

    scored = prepare_league_scoring_quantiles(_qb_components(include_minor=False), config)

    assert scored.loc[0, "league_scoring_source"] == "generic_points_fallback"
    assert bool(scored.loc[0, "league_scoring_fallback"]) is True
    assert float(scored.loc[0, "league_scoring_coverage"]) < 1.0
    assert float(scored.loc[0, "valuation_points_q50"]) == 260.0


def test_complete_nonzero_component_contract_can_be_component_rescored() -> None:
    config = LeagueConfig(scoring="ppr")

    scored = prepare_league_scoring_quantiles(_qb_components(include_minor=True), config)

    assert scored.loc[0, "league_scoring_source"] == "component_quantile_rescore"
    assert bool(scored.loc[0, "league_scoring_fallback"]) is False
    assert float(scored.loc[0, "league_scoring_coverage"]) == 1.0


def test_explicit_zero_weights_remove_components_from_exactness_contract() -> None:
    config = LeagueConfig(
        scoring="ppr",
        scoring_weights={"fumbles_lost": 0.0, "two_point_conversions": 0.0},
    )

    required = set(required_scoring_statistics("QB", config))
    scored = prepare_league_scoring_quantiles(_qb_components(include_minor=False), config)

    assert "fumbles_lost" not in required
    assert "two_point_conversions" not in required
    assert scored.loc[0, "league_scoring_source"] == "component_quantile_rescore"
    assert float(scored.loc[0, "league_scoring_coverage"]) == 1.0
