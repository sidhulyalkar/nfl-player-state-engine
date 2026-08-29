from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.fantasy.preseason import _normalize_opening_roster


def test_status_short_description_overrides_opaque_status_id() -> None:
    rosters = pd.DataFrame(
        [
            {
                "season": 2023,
                "week": 1,
                "team": "AAA",
                "position": "WR",
                "gsis_id": "P1",
                "full_name": "Exempt Player",
                "status": "E01",
                "status_description_abbr": "E01",
                "status_short_description": "Ex/Internat",
            },
            {
                "season": 2023,
                "week": 1,
                "team": "AAA",
                "position": "RB",
                "gsis_id": "P2",
                "full_name": "Waived Player",
                "status": "CUT",
                "status_description_abbr": "W03",
                "status_short_description": "Waivers/No Rec.",
            },
        ]
    )

    normalized, diagnostics = _normalize_opening_roster(
        rosters,
        season=2023,
        snapshot_week=1,
    )

    assert normalized["player_id"].tolist() == ["P1"]
    assert normalized.iloc[0]["roster_status"] == "EXEMPT"
    assert diagnostics.excluded_status_rows == 1
    assert diagnostics.unknown_status_rows == 0


def test_documented_status_ids_work_when_description_is_absent() -> None:
    rosters = pd.DataFrame(
        [
            {
                "season": 2024,
                "week": 1,
                "team": "AAA",
                "position": "QB",
                "gsis_id": "P1",
                "full_name": "Active Player",
                "status_description_abbr": "A01",
            },
            {
                "season": 2024,
                "week": 1,
                "team": "AAA",
                "position": "WR",
                "gsis_id": "P2",
                "full_name": "IR Player",
                "status_description_abbr": "R01",
            },
        ]
    )

    normalized, diagnostics = _normalize_opening_roster(
        rosters,
        season=2024,
        snapshot_week=1,
    )

    assert set(normalized["roster_status"]) == {"ACTIVE", "RESERVE"}
    assert diagnostics.unknown_status_rows == 0


def test_unresolvable_status_semantics_still_fail_closed() -> None:
    rosters = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "team": "AAA",
                "position": "TE",
                "gsis_id": "P1",
                "full_name": "Unknown Player",
                "status": "ZZ9",
                "status_description_abbr": "ZZ9",
            }
        ]
    )

    with pytest.raises(ValueError, match="Unknown roster status semantics"):
        _normalize_opening_roster(rosters, season=2025, snapshot_week=1)
