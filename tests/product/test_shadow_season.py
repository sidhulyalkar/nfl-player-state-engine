from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from player_state_engine.product.shadow_season import (
    ShadowSeasonStore,
    attach_research_challenger,
    build_shadow_settlement,
    build_shadow_snapshot,
    normalize_production_forecasts,
)


def _production() -> pd.DataFrame:
    return normalize_production_forecasts(
        pd.DataFrame(
            {
                "player_id": ["p1", "p2"],
                "player_name": ["Player One", "Player Two"],
                "position": ["WR", "RB"],
                "team": ["SF", "DET"],
                "week_points_q10": [6.0, 5.0],
                "week_points_q50": [12.0, 10.0],
                "week_points_q90": [20.0, 18.0],
                "availability_probability": [0.95, 0.90],
            }
        )
    )


def _snapshot(*, q50_delta: float = 0.0) -> dict[str, object]:
    frame = _production()
    frame.loc[0, "production_q50"] += q50_delta
    cutoff = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    return build_shadow_snapshot(
        frame,
        season=2026,
        week=1,
        checkpoint="WEDNESDAY",
        prediction_cutoff=cutoff,
        captured_at=cutoff + timedelta(minutes=5),
        league_key="sleeper:test",
        sources=[
            {
                "name": "production_projections",
                "available_at": cutoff - timedelta(minutes=10),
                "sha256": "a" * 64,
                "path": "artifacts/predictions.csv",
            }
        ],
        model_metadata={"model_version": "test"},
    )


def test_snapshot_rejects_future_source_and_hindsight_decision_context() -> None:
    cutoff = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="became available after prediction cutoff"):
        build_shadow_snapshot(
            _production(),
            season=2026,
            week=1,
            checkpoint="WEDNESDAY",
            prediction_cutoff=cutoff,
            captured_at=cutoff + timedelta(minutes=1),
            sources=[
                {
                    "name": "late_news",
                    "available_at": cutoff + timedelta(seconds=1),
                }
            ],
        )

    with pytest.raises(ValueError, match="hindsight field"):
        build_shadow_snapshot(
            _production(),
            season=2026,
            week=1,
            checkpoint="WEDNESDAY",
            prediction_cutoff=cutoff,
            captured_at=cutoff + timedelta(minutes=1),
            decision_records=[{"player_id": "p1", "realized_value": 24.0}],
        )


def test_snapshot_store_is_idempotent_and_conflicts_fail_closed(tmp_path) -> None:
    store = ShadowSeasonStore(tmp_path)
    snapshot = _snapshot()
    assert store.save_snapshot(snapshot) is True
    assert store.save_snapshot(snapshot) is False

    changed = _snapshot(q50_delta=0.5)
    assert changed["snapshot_id"] == snapshot["snapshot_id"]
    assert changed["content_sha256"] != snapshot["content_sha256"]
    with pytest.raises(ValueError, match="Immutable shadow checkpoint conflict"):
        store.save_snapshot(changed)


def test_snapshot_integrity_detects_local_tampering(tmp_path) -> None:
    store = ShadowSeasonStore(tmp_path)
    snapshot = _snapshot()
    store.save_snapshot(snapshot)
    path = store.snapshot_path(snapshot)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["forecasts"][0]["production_q50"] = 999.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="integrity check failed"):
        store.load_snapshot(str(snapshot["snapshot_id"]))


def test_challenger_is_attached_research_only() -> None:
    production = _production()
    challenger = pd.DataFrame(
        {
            "player_id": ["p1", "p2"],
            "q10": [7.0, 4.0],
            "q50": [13.0, 9.0],
            "q90": [21.0, 17.0],
            "probability_active": [0.94, 0.88],
        }
    )
    attached = attach_research_challenger(production, challenger)
    assert attached["challenger_authority"].eq("research_only").all()
    assert attached["challenger_may_change_decision"].eq(False).all()  # noqa: E712
    assert attached.loc[0, "production_q50"] == 12.0
    assert attached.loc[0, "challenger_q50"] == 13.0


def test_settlement_is_append_only_companion_and_summary_is_calibrated(tmp_path) -> None:
    store = ShadowSeasonStore(tmp_path)
    production = attach_research_challenger(
        _production(),
        pd.DataFrame(
            {
                "player_id": ["p1", "p2"],
                "q10": [7.0, 4.0],
                "q50": [13.0, 9.0],
                "q90": [21.0, 17.0],
            }
        ),
    )
    cutoff = datetime(2026, 9, 9, 18, 0, tzinfo=UTC)
    snapshot = build_shadow_snapshot(
        production,
        season=2026,
        week=1,
        checkpoint="WEDNESDAY",
        prediction_cutoff=cutoff,
        captured_at=cutoff + timedelta(minutes=5),
        sources=[{"name": "projections", "available_at": cutoff}],
    )
    original_digest = snapshot["content_sha256"]
    assert store.save_snapshot(snapshot) is True

    actuals = pd.DataFrame({"player_id": ["p1", "p2"], "actual": [14.0, 8.0]})
    settlement = build_shadow_settlement(snapshot, actuals)
    assert settlement["snapshot_content_sha256"] == original_digest
    assert settlement["metrics"]["production"]["n"] == 2
    assert settlement["metrics"]["production"]["q50_mae"] == pytest.approx(2.0)
    assert settlement["metrics"]["challenger"]["n"] == 2
    assert store.save_settlement(settlement) is True
    assert store.save_settlement(settlement) is False
    assert store.load_snapshot(str(snapshot["snapshot_id"]))["content_sha256"] == original_digest

    changed_actuals = pd.DataFrame({"player_id": ["p1", "p2"], "actual": [30.0, 8.0]})
    changed_settlement = build_shadow_settlement(snapshot, changed_actuals)
    with pytest.raises(ValueError, match="Immutable shadow settlement conflict"):
        store.save_settlement(changed_settlement)

    summary = store.summary(season=2026)
    assert summary["data_mode"] == "LIVE_SHADOW"
    assert summary["snapshot_count"] == 1
    assert summary["settlement_count"] == 1
    assert summary["health"]["integrity_verified"] is True
    assert summary["overall"]["production"]["n"] == 2
    wednesday = next(
        row for row in summary["by_checkpoint"] if row["checkpoint"] == "WEDNESDAY"
    )
    assert wednesday["settled_snapshots"] == 1


def test_settlement_requires_complete_actuals_by_default() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValueError, match="missing actuals"):
        build_shadow_settlement(
            snapshot,
            pd.DataFrame({"player_id": ["p1"], "actual": [14.0]}),
        )


def test_conflicting_projection_aliases_fail_closed() -> None:
    frame = pd.DataFrame(
        {
            "player_id": ["p1"],
            "week_points_q10": [5.0],
            "fantasy_points_ppr_q10": [6.0],
            "week_points_q50": [10.0],
            "week_points_q90": [15.0],
        }
    )
    with pytest.raises(ValueError, match="Conflicting aliases for production_q10"):
        normalize_production_forecasts(frame)
