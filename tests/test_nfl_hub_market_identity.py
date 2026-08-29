from __future__ import annotations

import pandas as pd

from player_state_engine.product.nfl_hub import canonicalize_rankings


def _playerids() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "gsis_id": "00-0034857",
                "fantasypros_id": 17298.0,
                "sportradar_id": "sr:player:josh-allen",
                "yahoo_id": 30977.0,
                "name": "Josh Allen",
            },
            {
                "gsis_id": "00-0041027",
                "fantasypros_id": 25403.0,
                "sportradar_id": "sr:player:jeremiyah-love",
                "yahoo_id": 42001.0,
                "name": "Jeremiyah Love",
            },
        ]
    )


def test_integer_like_external_ids_resolve_across_float_and_int_representations() -> None:
    rankings = pd.DataFrame(
        [
            {"id": 17298, "rank": 3, "ecr_type": "ro", "page_type": "redraft-overall"},
            {"id": 25403, "rank": 21, "ecr_type": "ro", "page_type": "redraft-overall"},
        ]
    )

    result = canonicalize_rankings(rankings, _playerids())

    assert list(result["player_id"]) == ["00-0034857", "00-0041027"]
    assert set(result["market_identity_source"]) == {"fantasypros_id"}
    diagnostics = result.attrs["identity_diagnostics"]
    assert diagnostics["resolved_rows"] == 2
    assert diagnostics["resolved_redraft_rows"] == 2
    assert diagnostics["redraft_identity_coverage"] == 1.0
    assert diagnostics["usable_market_players"] == 2


def test_conflicting_exact_ids_fail_closed_instead_of_choosing_one_route() -> None:
    rankings = pd.DataFrame(
        [
            {
                "id": 17298,
                "sportradar_id": "sr:player:jeremiyah-love",
                "rank": 3,
                "ecr_type": "ro",
                "page_type": "redraft-overall",
            }
        ]
    )

    result = canonicalize_rankings(rankings, _playerids())

    assert result.empty
    diagnostics = result.attrs["identity_diagnostics"]
    assert diagnostics["conflict_rows"] == 1
    assert diagnostics["usable_market_players"] == 0


def test_player_names_never_resolve_market_identity() -> None:
    rankings = pd.DataFrame(
        [
            {
                "player_name": "Josh Allen",
                "rank": 3,
                "ecr_type": "ro",
                "page_type": "redraft-overall",
            }
        ]
    )

    result = canonicalize_rankings(rankings, _playerids())

    assert result.empty
    assert result.attrs["identity_diagnostics"]["unresolved_rows"] == 1


def test_best_ball_rows_do_not_substitute_for_redraft_market_truth() -> None:
    rankings = pd.DataFrame(
        [
            {
                "id": 17298,
                "rank": 3,
                "ecr_type": "bb",
                "page_type": "best-ball-overall",
            }
        ]
    )

    result = canonicalize_rankings(rankings, _playerids())

    assert result.empty
    diagnostics = result.attrs["identity_diagnostics"]
    assert diagnostics["resolved_rows"] == 1
    assert diagnostics["redraft_rows"] == 0
    assert diagnostics["usable_market_players"] == 0
