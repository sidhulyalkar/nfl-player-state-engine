from __future__ import annotations

import pandas as pd

from player_state_engine.product.nfl_hub import (
    canonicalize_depth_charts,
    canonicalize_rankings,
)


def test_current_depth_chart_schema_uses_latest_dt() -> None:
    frame = pd.DataFrame(
        [
            {
                "dt": "2026-08-27T10:00:00Z",
                "team": "AAA",
                "player_name": "Player One",
                "gsis_id": "00-001",
                "pos_abb": "RB",
                "pos_rank": 3,
            },
            {
                "dt": "2026-08-28T10:00:00Z",
                "team": "AAA",
                "player_name": "Player One",
                "gsis_id": "00-001",
                "pos_abb": "RB",
                "pos_rank": 1,
            },
        ]
    )
    result = canonicalize_depth_charts(frame, season=2026)
    assert len(result) == 1
    assert result.iloc[0]["depth_rank"] == 1
    assert result.iloc[0]["depth_team"] == "AAA"


def test_fantasypros_rankings_resolve_by_multiple_exact_ids_without_names() -> None:
    rankings = pd.DataFrame(
        [
            {
                "ecr_type": "ro",
                "page_type": "redraft-overall",
                "player": "Rookie One",
                "id": "FP-ROOKIE-MISSING",
                "sportsdata_id": "SR-1",
                "yahoo_id": "Y-1",
                "ecr": 17.0,
            },
            {
                "ecr_type": "ro",
                "page_type": "redraft-overall",
                "player": "Veteran Two",
                "id": "FP-2",
                "sportsdata_id": "SR-2",
                "yahoo_id": "Y-2",
                "ecr": 33.0,
            },
        ]
    )
    playerids = pd.DataFrame(
        [
            {
                "gsis_id": "00-001",
                "fantasypros_id": None,
                "sportradar_id": "SR-1",
                "yahoo_id": "Y-1",
            },
            {
                "gsis_id": "00-002",
                "fantasypros_id": "FP-2",
                "sportradar_id": "SR-2",
                "yahoo_id": "Y-2",
            },
        ]
    )
    result = canonicalize_rankings(rankings, playerids)
    by_id = result.set_index("player_id")
    assert by_id.loc["00-001", "market_rank"] == 17.0
    assert "sportradar_id" in by_id.loc["00-001", "market_identity_source"]
    assert by_id.loc["00-002", "market_rank"] == 33.0
    assert result.attrs["identity_diagnostics"]["identity_coverage"] == 1.0


def test_conflicting_external_ids_fail_closed_instead_of_name_matching() -> None:
    rankings = pd.DataFrame(
        [
            {
                "ecr_type": "ro",
                "page_type": "redraft-overall",
                "player": "Ambiguous Player",
                "id": "FP-1",
                "sportsdata_id": "SR-2",
                "ecr": 50.0,
            }
        ]
    )
    playerids = pd.DataFrame(
        [
            {"gsis_id": "00-001", "fantasypros_id": "FP-1", "sportradar_id": "SR-1"},
            {"gsis_id": "00-002", "fantasypros_id": "FP-2", "sportradar_id": "SR-2"},
        ]
    )
    result = canonicalize_rankings(rankings, playerids)
    diagnostics = result.attrs["identity_diagnostics"]
    assert result.empty
    assert diagnostics["conflict_rows"] == 1
    assert diagnostics["unresolved_rows"] == 1


def test_bestball_only_row_is_not_used_as_redraft_market_truth() -> None:
    rankings = pd.DataFrame(
        [
            {
                "ecr_type": "bp",
                "page_type": "best-rb",
                "id": "FP-1",
                "ecr": 4.0,
            }
        ]
    )
    playerids = pd.DataFrame([{"gsis_id": "00-001", "fantasypros_id": "FP-1"}])
    result = canonicalize_rankings(rankings, playerids)
    assert result.empty
