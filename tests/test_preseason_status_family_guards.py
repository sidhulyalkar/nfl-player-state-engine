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
