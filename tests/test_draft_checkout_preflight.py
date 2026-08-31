from __future__ import annotations

import csv
from pathlib import Path

from scripts.check_draft_checkout import _projection_contract_check


def _write_projection(path: Path, *, rows_per_contract: int = 250) -> None:
    fields = [
        "scoring_contract_id",
        "player_id",
        "league_season_points_q50",
        "league_scoring_exact",
        "decision_quantile_policy",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for contract, policy in (
            ("scoring-v1-ppr", "qualified_distribution"),
            ("scoring-v1-half", "q50_only"),
        ):
            for index in range(rows_per_contract):
                writer.writerow(
                    {
                        "scoring_contract_id": contract,
                        "player_id": f"p{index:03d}",
                        "league_season_points_q50": 100.0 + index,
                        "league_scoring_exact": "true",
                        "decision_quantile_policy": policy,
                    }
                )


def test_projection_contract_preflight_accepts_current_multicontract_shape(tmp_path: Path) -> None:
    path = tmp_path / "product_player_values.csv"
    _write_projection(path)

    ok, detail = _projection_contract_check(path)

    assert ok is True
    assert "2 contracts" in detail
    assert "min_contract_rows=250" in detail
    assert "qualified_distribution" in detail
    assert "q50_only" in detail


def test_projection_contract_preflight_rejects_old_universal_shape(tmp_path: Path) -> None:
    path = tmp_path / "product_player_values.csv"
    path.write_text("player_id,season_points_q50\np1,123\n", encoding="utf-8")

    ok, detail = _projection_contract_check(path)

    assert ok is False
    assert "legacy/incomplete projection schema" in detail
    assert "scoring_contract_id" in detail


def test_projection_contract_preflight_rejects_duplicate_player_inside_contract(tmp_path: Path) -> None:
    path = tmp_path / "product_player_values.csv"
    _write_projection(path)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scoring_contract_id",
                "player_id",
                "league_season_points_q50",
                "league_scoring_exact",
                "decision_quantile_policy",
            ],
        )
        writer.writerow(
            {
                "scoring_contract_id": "scoring-v1-ppr",
                "player_id": "p000",
                "league_season_points_q50": 999.0,
                "league_scoring_exact": "true",
                "decision_quantile_policy": "qualified_distribution",
            }
        )

    ok, detail = _projection_contract_check(path)

    assert ok is False
    assert "duplicate contract/player rows" in detail
