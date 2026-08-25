from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from scripts.build_draft_survival_observations import build_observations


def _mixed_alias_rows() -> pd.DataFrame:
    draft_time = datetime(2025, 8, 12, 18, tzinfo=UTC)
    market_time = draft_time - timedelta(hours=8)
    rows: list[dict[str, object]] = []
    for pick in range(1, 13):
        row: dict[str, object] = {
            "draft_id": "mixed-alias-room",
            "player_id": f"p{pick:02d}",
            "actual_pick": pick,
            "market_adp": float(pick),
            "market_adp_sd": 4.0,
            "position": "WR" if pick % 2 else "RB",
            "teams": 4,
            "season": 2025,
            "platform": "sleeper",
            "scoring": "ppr",
        }
        if pick % 2:
            row["draft_started_at"] = draft_time.isoformat()
            row["market_snapshot_at"] = market_time.isoformat()
        else:
            row["draft_timestamp"] = draft_time.isoformat()
            row["adp_snapshot_at"] = market_time.isoformat()
        rows.append(row)
    return pd.DataFrame(rows)


def test_observation_builder_coalesces_timestamp_aliases_row_by_row() -> None:
    observations = build_observations(_mixed_alias_rows(), default_teams=4)

    assert not observations.empty
    assert observations["point_in_time_market_verified"].all()
    assert (observations["market_snapshot_age_hours"] == 8.0).all()
    assert set(observations["draft_timestamp_source"].dropna()) == {
        "draft_started_at",
        "draft_timestamp",
    }
    assert set(observations["market_timestamp_source"].dropna()) == {
        "market_snapshot_at",
        "adp_snapshot_at",
    }


def test_observation_builder_rejects_conflicting_timestamp_aliases() -> None:
    rows = _mixed_alias_rows()
    rows["draft_started_at"] = datetime(2025, 8, 12, 18, tzinfo=UTC).isoformat()
    rows.loc[rows.index[0], "draft_timestamp"] = datetime(
        2025, 8, 12, 19, tzinfo=UTC
    ).isoformat()

    with pytest.raises(ValueError, match="Conflicting draft-start timestamp aliases"):
        build_observations(rows, default_teams=4)
