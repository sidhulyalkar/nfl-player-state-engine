from __future__ import annotations

import hashlib
import json
from datetime import date

import pandas as pd
import pytest

from player_state_engine.evaluation.showcase_automation import (
    load_verified_shadow_showcase_model,
    resolve_regular_season_week,
)


def _digest(payload: dict[str, object]) -> str:
    clean = dict(payload)
    clean.pop("content_sha256", None)
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _shadow_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "snapshot_id": "shadow-week-1",
        "season": 2026,
        "week": 1,
        "checkpoint": "FINAL_DECISION",
        "prediction_cutoff": "2026-09-10T20:00:00+00:00",
        "captured_at": "2026-09-10T20:01:00+00:00",
        "forecasts": [
            {
                "player_id": "p1",
                "player_name": "One Player",
                "position": "WR",
                "production_q10": 8.0,
                "production_q50": 14.0,
                "production_q90": 23.0,
            },
            {
                "player_id": "p2",
                "player_name": "Two Player",
                "position": "WR",
                "production_q10": 6.0,
                "production_q50": 11.0,
                "production_q90": 19.0,
            },
        ],
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def test_verified_shadow_checkpoint_becomes_showcase_model(tmp_path) -> None:
    path = tmp_path / "shadow.json"
    path.write_text(json.dumps(_shadow_payload()), encoding="utf-8")

    model = load_verified_shadow_showcase_model(path, season=2026, week=1)

    assert model.snapshot_id == "shadow-week-1"
    assert model.source == "shadow_season:final_decision"
    assert model.prediction_cutoff_utc == "2026-09-10T20:00:00+00:00"
    assert model.frame["production_q50"].tolist() == [14.0, 11.0]


def test_shadow_checkpoint_tampering_fails_closed(tmp_path) -> None:
    payload = _shadow_payload()
    payload["forecasts"][0]["production_q50"] = 99.0  # type: ignore[index]
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="integrity verification"):
        load_verified_shadow_showcase_model(path, season=2026, week=1)


def test_shadow_checkpoint_rejects_wrong_week(tmp_path) -> None:
    path = tmp_path / "shadow.json"
    path.write_text(json.dumps(_shadow_payload()), encoding="utf-8")

    with pytest.raises(ValueError, match="week mismatch"):
        load_verified_shadow_showcase_model(path, season=2026, week=2)


def _schedule() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"season": 2026, "week": 1, "gameday": "2026-09-10", "game_type": "REG"},
            {"season": 2026, "week": 1, "gameday": "2026-09-14", "game_type": "REG"},
            {"season": 2026, "week": 2, "gameday": "2026-09-17", "game_type": "REG"},
            {"season": 2026, "week": 2, "gameday": "2026-09-21", "game_type": "REG"},
            {"season": 2026, "week": 3, "gameday": "2026-09-24", "game_type": "REG"},
            {"season": 2026, "week": 3, "gameday": "2026-09-28", "game_type": "REG"},
            {"season": 2026, "week": 1, "gameday": "2027-01-10", "game_type": "POST"},
        ]
    )


def test_capture_week_resolves_next_unstarted_week() -> None:
    week = resolve_regular_season_week(
        _schedule(),
        season=2026,
        phase="capture",
        as_of=date(2026, 9, 16),
    )
    assert week == 2


def test_settlement_week_resolves_latest_completed_week() -> None:
    week = resolve_regular_season_week(
        _schedule(),
        season=2026,
        phase="settle",
        as_of=date(2026, 9, 22),
    )
    assert week == 2


def test_settlement_fails_before_any_week_is_complete() -> None:
    with pytest.raises(ValueError, match="No completed regular-season week"):
        resolve_regular_season_week(
            _schedule(),
            season=2026,
            phase="settle",
            as_of=date(2026, 9, 9),
        )
