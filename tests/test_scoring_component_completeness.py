from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import (
    prepare_league_scoring_quantiles,
    required_scoring_statistics,
)


def _wr(include_minor: bool) -> pd.DataFrame:
    row: dict[str, object] = {
        "player_id": "wr1",
        "player_name": "WR One",
        "position": "WR",
        "season_points_q10": 100.0,
        "season_points_q50": 150.0,
        "season_points_q90": 210.0,
    }
    for statistic in ("receptions", "receiving_yards", "receiving_tds"):
        row[f"{statistic}_q10"] = 1.0
        row[f"{statistic}_q50"] = 2.0
        row[f"{statistic}_q90"] = 3.0
    if include_minor:
        for statistic in ("fumbles_lost", "two_point_conversions"):
            row[f"{statistic}_q10"] = 0.0
            row[f"{statistic}_q50"] = 0.0
            row[f"{statistic}_q90"] = 1.0
    return pd.DataFrame([row])


def test_missing_nonzero_minor_terms_prevents_complete_component_rescore() -> None:
    scored = prepare_league_scoring_quantiles(_wr(include_minor=False), LeagueConfig(scoring="ppr"))
    row = scored.iloc[0]
    assert row["league_scoring_source"] == "generic_points_fallback"
    assert float(row["league_scoring_coverage"]) == 0.6
    assert bool(row["league_scoring_exact"]) is False


def test_complete_component_rescore_remains_approximate() -> None:
    scored = prepare_league_scoring_quantiles(_wr(include_minor=True), LeagueConfig(scoring="ppr"))
    row = scored.iloc[0]
    assert row["league_scoring_source"] == "component_quantile_rescore"
    assert float(row["league_scoring_coverage"]) == 1.0
    assert bool(row["league_scoring_exact"]) is False
    assert bool(row["league_scoring_approximate"]) is True


def test_explicit_zero_weights_remove_minor_terms_from_completeness_contract() -> None:
    config = LeagueConfig(
        scoring="ppr",
        scoring_weights={"fumbles_lost": 0.0, "two_point_conversions": 0.0},
    )
    scored = prepare_league_scoring_quantiles(_wr(include_minor=False), config)
    row = scored.iloc[0]
    assert row["league_scoring_source"] == "component_quantile_rescore"
    assert float(row["league_scoring_coverage"]) == 1.0
    assert bool(row["league_scoring_exact"]) is False


def test_tight_end_premium_requires_receptions_even_when_base_reception_weight_is_zero() -> None:
    config = LeagueConfig(scoring="standard", tight_end_premium=1.0)
    required = required_scoring_statistics("TE", config)
    assert "receptions" in required
    assert "fumbles_lost" in required
    assert "two_point_conversions" in required
