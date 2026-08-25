from __future__ import annotations

import copy
import sys
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))
import run_current_week_official_availability_v3 as exploratory  # noqa: E402
import run_registered_current_week_official_availability_v3 as registered  # noqa: E402


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2024,
                "week": 2,
                "game_id": "2024_02_A_B",
                "player_id": "p1",
                "recent_team": "A",
                "position": "WR",
            }
        ]
    )


def _schedule() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2024,
                "week": 2,
                "game_id": "2024_02_A_B",
                "gameday": "2024-09-15",
                "gametime": "13:00",
            }
        ]
    )


def _injury_row(
    player_id: str,
    *,
    week: int,
    modified: str,
    practice: str = "Limited Participation in Practice",
    report: str = "Questionable",
) -> dict[str, object]:
    return {
        "season": 2024,
        "week": week,
        "gsis_id": player_id,
        "full_name": player_id,
        "team": "A",
        "position": "WR",
        "practice_status": practice,
        "report_status": report,
        "date_modified": modified,
    }


def test_source_covered_current_week_absence_resets_stale_prior_week_claim() -> None:
    injuries = pd.DataFrame(
        [
            _injury_row("p1", week=1, modified="2024-09-08T14:00:00Z"),
            # A different current-week player proves the team injury source is observable.
            _injury_row("p2", week=2, modified="2024-09-15T14:00:00Z"),
        ]
    )

    frame, preflight = exploratory._build_current_week_frame(_features(), _schedule(), injuries)
    row = frame.iloc[0]

    assert bool(row["official_availability_source_covered"])
    assert row["cw_practice_found"] == 0
    assert row["cw_game_found"] == 0
    assert row["cw_any_report_found"] == 0
    assert pd.isna(row["cw_practice_score"])
    assert pd.isna(row["cw_game_score"])
    assert preflight["source_coverage"] == 1.0
    assert preflight["any_report_prevalence"] == 0.0


def test_current_week_long_form_practice_and_game_designation_are_preserved() -> None:
    injuries = pd.DataFrame(
        [_injury_row("p1", week=2, modified="2024-09-15T14:00:00Z")]
    )

    frame, preflight = exploratory._build_current_week_frame(_features(), _schedule(), injuries)
    row = frame.iloc[0]

    assert row["cw_practice_found"] == 1
    assert row["cw_game_found"] == 1
    assert row["cw_any_report_found"] == 1
    assert float(row["cw_practice_score"]) == pytest.approx(0.65)
    assert float(row["cw_game_score"]) == pytest.approx(0.72)
    assert float(row["cw_practice_is_limited"]) == 1.0
    assert float(row["cw_game_is_questionable"]) == 1.0
    assert preflight["latest_evidence_after_cutoff_rows"] == 0


def test_future_current_week_update_is_not_allowed_into_prediction_state() -> None:
    injuries = pd.DataFrame(
        [
            # This row is after the 15:30 UTC prediction cutoff and must be excluded.
            _injury_row("p1", week=2, modified="2024-09-15T16:00:00Z", report="Out"),
            # This row establishes that the team source itself was observable before cutoff.
            _injury_row("p2", week=2, modified="2024-09-15T14:00:00Z"),
        ]
    )

    frame, _ = exploratory._build_current_week_frame(_features(), _schedule(), injuries)
    row = frame.iloc[0]

    assert bool(row["official_availability_source_covered"])
    assert row["cw_any_report_found"] == 0
    assert pd.isna(row["cw_game_score"])
    assert pd.isna(row["date_modified"])


def test_registered_v3_contract_matches_executable_and_refuses_parameter_drift() -> None:
    registry = registered._load_registry(registered.REGISTRY_PATH)
    registered._assert_static_contract(registry)

    drifted = copy.deepcopy(registry)
    drifted["evaluation_contract"]["bootstrap_samples"] = 1000
    with pytest.raises(ValueError, match="bootstrap_samples"):
        registered._assert_static_contract(drifted)

    drifted = copy.deepcopy(registry)
    drifted["evaluation_contract"]["seed"] = 7
    with pytest.raises(ValueError, match="seed"):
        registered._assert_static_contract(drifted)

    drifted = copy.deepcopy(registry)
    drifted["formulations"]["practice_current_week"].append("availability_old_claim")
    with pytest.raises(ValueError, match="formulation registry"):
        registered._assert_static_contract(drifted)


def test_v3_authority_cannot_self_promote(tmp_path: Path) -> None:
    registry = registered._load_registry(registered.REGISTRY_PATH)

    promoted = copy.deepcopy(registry)
    promoted["automatic_promotion"] = True
    path = tmp_path / "v3-promoted-registry.json"
    path.write_text(__import__("json").dumps(promoted), encoding="utf-8")
    with pytest.raises(ValueError, match="automatic promotion"):
        registered._load_registry(path)

    activation = copy.deepcopy(registry)
    activation["eligible_for_activation_review"] = True
    path.write_text(__import__("json").dumps(activation), encoding="utf-8")
    with pytest.raises(ValueError, match="self-authorize activation review"):
        registered._load_registry(path)
