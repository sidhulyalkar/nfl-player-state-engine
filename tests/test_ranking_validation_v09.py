from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.evaluation.ranking_validation import (
    compare_rankings,
    default_format_scenarios,
    run_format_matrix,
    structural_monotonicity_checks,
)
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.rankings import (
    attach_external_ranking_context,
    normalize_ranking_frame,
)


def _projection_pool() -> pd.DataFrame:
    rows = []
    counts = {"QB": 48, "RB": 72, "WR": 84, "TE": 36}
    starts = {"QB": 410.0, "RB": 330.0, "WR": 320.0, "TE": 250.0}
    slopes = {"QB": 5.0, "RB": 3.2, "WR": 2.5, "TE": 4.0}
    for position, count in counts.items():
        for rank in range(1, count + 1):
            q50 = max(30.0, starts[position] - slopes[position] * rank)
            rows.append(
                {
                    "player_id": f"{position}{rank}",
                    "player_name": f"{position} Player {rank}",
                    "position": position,
                    "season_points_q10": q50 * 0.70,
                    "season_points_q50": q50,
                    "season_points_q90": q50 * 1.30,
                }
            )
    return pd.DataFrame(rows)


def test_format_matrix_has_no_qb_monotonicity_failures() -> None:
    boards, summary, _ = run_format_matrix(
        _projection_pool(), scenarios=default_format_scenarios()
    )
    checks = structural_monotonicity_checks(boards, summary)
    relevant = [check for check in checks if "qb" in check.name]
    assert relevant
    assert all(check.status == "PASS" for check in relevant)


def test_external_rankings_match_identity_and_remain_audit_only() -> None:
    board = pd.DataFrame(
        {
            "player_id": ["p1", "p2"],
            "player_name": ["AJ Brown", "Josh Allen"],
            "position": ["WR", "QB"],
            "nfl_team": ["PHI", "BUF"],
            "live_rank": [1, 2],
            "live_draft_score": [90.0, 88.0],
        }
    )
    first = normalize_ranking_frame(
        pd.DataFrame(
            {
                "player": ["A.J. Brown", "Josh Allen"],
                "pos": ["WR", "QB"],
                "team": ["PHI", "BUF"],
                "rank": [10, 2],
            }
        ),
        source="fantasy_life",
        scoring="half_ppr",
        teams=12,
        qb_format_name="2qb",
    )
    second = normalize_ranking_frame(
        pd.DataFrame(
            {
                "player_name": ["AJ Brown", "Josh Allen"],
                "position": ["WR", "QB"],
                "nfl_team": ["PHI", "BUF"],
                "rank": [12, 1],
            }
        ),
        source="rotowire",
        scoring="half_ppr",
        teams=12,
        qb_format_name="2qb",
    )
    config = LeagueConfig(teams=12, scoring="half_ppr", roster_slots={"QB": 2, "WR": 2})
    enriched, metadata = attach_external_ranking_context(
        board, pd.concat([first, second], ignore_index=True), config
    )
    aj = enriched.set_index("player_id").loc["p1"]
    assert aj.external_source_count == 2
    assert np.isclose(aj.external_consensus_rank, 11.0)
    assert np.isclose(aj.model_vs_external_rank_delta, 10.0)
    assert metadata["external_values_are_audit_only"] is True
    assert enriched["live_draft_score"].tolist() == [90.0, 88.0]


def test_rank_metrics_capture_order_agreement() -> None:
    left = pd.DataFrame({"player_id": ["a", "b", "c"], "rank": [1, 2, 3]})
    right = pd.DataFrame({"player_id": ["a", "b", "c"], "rank": [2, 4, 6]})
    metrics = compare_rankings(left, right)
    assert metrics.rows == 3
    assert np.isclose(metrics.spearman, 1.0)
    assert np.isclose(metrics.kendall, 1.0)
