from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.draft_actionability import assess_candidate_scope_actionability
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness
from player_state_engine.fantasy.scoring import (
    aggregate_scored_draws,
    prepare_league_scoring_quantiles,
)


def _component_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, position in enumerate(("QB", "RB", "WR", "TE"), start=1):
        row: dict[str, object] = {
            "player_id": f"{position}{index}",
            "position": position,
            "market_adp": float(index * 10),
        }
        for quantile, scale in ((10, 0.8), (50, 1.0), (90, 1.2)):
            row.update(
                {
                    f"passing_yards_q{quantile}": 4000.0 * scale,
                    f"passing_tds_q{quantile}": 28.0 * scale,
                    f"interceptions_q{quantile}": 12.0 * scale,
                    f"rushing_yards_q{quantile}": 700.0 * scale,
                    f"rushing_tds_q{quantile}": 7.0 * scale,
                    f"receptions_q{quantile}": 75.0 * scale,
                    f"receiving_yards_q{quantile}": 950.0 * scale,
                    f"receiving_tds_q{quantile}": 7.0 * scale,
                    f"fumbles_lost_q{quantile}": 1.0 * scale,
                    f"two_point_conversions_q{quantile}": 0.5 * scale,
                }
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _provided_rows(*, exact: bool | None) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {"player_id": "QB1", "position": "QB", "market_adp": 10.0},
            {"player_id": "RB1", "position": "RB", "market_adp": 20.0},
            {"player_id": "WR1", "position": "WR", "market_adp": 30.0},
            {"player_id": "TE1", "position": "TE", "market_adp": 40.0},
        ]
    )
    frame["league_season_points_q10"] = [220.0, 150.0, 140.0, 90.0]
    frame["league_season_points_q50"] = [280.0, 220.0, 210.0, 155.0]
    frame["league_season_points_q90"] = [340.0, 300.0, 290.0, 230.0]
    if exact is not None:
        frame["league_scoring_exact"] = exact
    return frame


def test_component_quantile_rescore_is_usable_but_never_exact() -> None:
    scored = prepare_league_scoring_quantiles(_component_rows(), LeagueConfig())

    assert scored["valuation_points_q50"].notna().all()
    assert set(scored["league_scoring_source"]) == {"component_quantile_rescore"}
    assert scored["league_scoring_coverage"].eq(1.0).all()
    assert scored["league_scoring_exact"].eq(False).all()
    assert scored["league_scoring_approximate"].eq(True).all()

    readiness = assess_league_readiness(_component_rows(), LeagueConfig())
    assert readiness.ready is False
    assert readiness.valuation_coverage == 1.0
    assert readiness.exact_scoring_coverage == 0.0
    assert readiness.approximate_scoring_coverage == 1.0
    assert set(readiness.inexact_required_positions) == {"QB", "RB", "WR", "TE"}
    assert "INEXACT_SCORING_APPROXIMATION" in readiness.flags
    assert "INEXACT_REQUIRED_POSITION_SCORING" in readiness.blocking_flags


def test_provided_league_quantiles_require_explicit_exact_declaration() -> None:
    unverified = prepare_league_scoring_quantiles(_provided_rows(exact=None), LeagueConfig())
    assert set(unverified["league_scoring_source"]) == {"provided_league_quantiles_unverified"}
    assert unverified["league_scoring_exact"].eq(False).all()
    assert assess_league_readiness(_provided_rows(exact=None), LeagueConfig()).ready is False

    verified = prepare_league_scoring_quantiles(_provided_rows(exact=True), LeagueConfig())
    assert set(verified["league_scoring_source"]) == {"verified_league_quantiles"}
    assert verified["league_scoring_exact"].eq(True).all()
    report = assess_league_readiness(_provided_rows(exact=True), LeagueConfig())
    assert report.ready is True
    assert report.exact_scoring_coverage == 1.0
    assert report.inexact_required_positions == ()


def test_candidate_scope_blocks_component_quantile_approximation() -> None:
    projections = _component_rows()
    candidates = projections.loc[
        projections["position"].isin(["RB", "WR"]), ["player_id", "position"]
    ]

    report = assess_candidate_scope_actionability(projections, candidates, LeagueConfig())

    assert report.actionable is False
    assert report.exact_scoring_coverage == 0.0
    assert "CANDIDATE_INEXACT_SCORING_APPROXIMATION" in report.blocking_reasons


def test_candidate_scope_accepts_explicit_verified_league_distribution() -> None:
    projections = _provided_rows(exact=True)
    candidates = projections.loc[
        projections["position"].isin(["RB", "WR"]), ["player_id", "position"]
    ]

    report = assess_candidate_scope_actionability(projections, candidates, LeagueConfig())

    assert report.actionable is True
    assert report.exact_scoring_coverage == 1.0
    assert report.blocking_reasons == ()


def test_correlated_draw_aggregation_marks_scoring_exact() -> None:
    draws = pd.DataFrame(
        {
            "player_id": ["p1", "p1", "p1", "p2", "p2", "p2"],
            "league_fantasy_points": [10.0, 20.0, 30.0, 5.0, 10.0, 15.0],
        }
    )

    result = aggregate_scored_draws(
        draws,
        quantiles=(0.10, 0.50, 0.90),
        prefix="league_season_points",
    )

    assert result["league_scoring_exact"].eq(True).all()
    assert result["league_scoring_approximate"].eq(False).all()
    assert set(result["league_scoring_source"]) == {"correlated_draw_rescore"}
