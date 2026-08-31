from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.fantasy.preseason import _normalize_opening_roster


def test_opaque_e_family_is_broadly_exempt() -> None:
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
            }
        ]
    )
    normalized, diagnostics = _normalize_opening_roster(
        rosters,
        season=2023,
        snapshot_week=1,
    )
    assert normalized.iloc[0]["roster_status"] == "EXEMPT"
    assert diagnostics.unknown_status_rows == 0


def test_current_a02_is_exactly_reserve_without_generalizing_a_family() -> None:
    rosters = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 1,
                "team": "AAA",
                "position": "RB",
                "gsis_id": "P-A02",
                "full_name": "Reserve Player",
                "status": "A02",
                "status_description_abbr": "A02",
            }
        ]
    )
    normalized, diagnostics = _normalize_opening_roster(
        rosters,
        season=2026,
        snapshot_week=1,
    )
    assert normalized.iloc[0]["roster_status"] == "RESERVE"
    assert diagnostics.unknown_status_rows == 0

    unknown = rosters.copy()
    unknown.loc[:, "status"] = "A99"
    unknown.loc[:, "status_description_abbr"] = "A99"
    with pytest.raises(ValueError, match="Unknown roster status semantics"):
        _normalize_opening_roster(unknown, season=2026, snapshot_week=1)


def test_unknown_r_family_does_not_inherit_reserve_semantics() -> None:
    rosters = pd.DataFrame(
        [
            {
                "season": 2023,
                "week": 1,
                "team": "AAA",
                "position": "RB",
                "gsis_id": "P2",
                "full_name": "Unknown Reserve Family",
                "status": "R99",
                "status_description_abbr": "R99",
            }
        ]
    )
    with pytest.raises(ValueError, match="Unknown roster status semantics"):
        _normalize_opening_roster(rosters, season=2023, snapshot_week=1)
