from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from player_state_engine.fantasy.draft_market_archive import (
    archive_sleeper_draft,
    asof_join_market_snapshots,
    load_archived_draft,
    normalize_archive,
    normalize_sleeper_draft,
)
from player_state_engine.fantasy.rankings import normalize_ranking_frame


def _draft(*, draft_id: str = "draft-1", start: datetime | None = None) -> dict[str, object]:
    start = start or datetime(2025, 8, 15, 18, tzinfo=UTC)
    return {
        "draft_id": draft_id,
        "league_id": "league-1",
        "season": "2025",
        "status": "complete",
        "type": "snake",
        "start_time": int(start.timestamp() * 1000),
        "settings": {
            "teams": 4,
            "slots_qb": 1,
            "slots_rb": 2,
            "slots_wr": 2,
            "slots_te": 1,
            "slots_flex": 1,
            "slots_bn": 5,
        },
        "metadata": {"scoring_type": "ppr"},
    }


def _picks() -> list[dict[str, object]]:
    names = [
        ("Alpha", "Runner", "RB", "ARI"),
        ("Bravo", "Target", "WR", "BUF"),
        ("Charlie", "Passer", "QB", "CIN"),
        ("Delta", "Tight", "TE", "DAL"),
    ]
    rows: list[dict[str, object]] = []
    for index, (first, last, position, team) in enumerate(names, start=1):
        rows.append(
            {
                "draft_id": "draft-1",
                "player_id": f"s{index}",
                "pick_no": index,
                "round": 1,
                "draft_slot": index,
                "picked_by": f"u{index}",
                "roster_id": str(index),
                "metadata": {
                    "first_name": first,
                    "last_name": last,
                    "position": position,
                    "team": team,
                },
            }
        )
    return rows


def test_archive_is_idempotent_but_refuses_changed_payload(tmp_path) -> None:
    draft = _draft()
    picks = _picks()
    first = archive_sleeper_draft(
        tmp_path,
        draft=draft,
        picks=picks,
        traded_picks=[],
        retrieved_at=datetime(2025, 8, 20, tzinfo=UTC),
    )
    second = archive_sleeper_draft(
        tmp_path,
        draft=draft,
        picks=picks,
        traded_picks=[],
        retrieved_at=datetime(2025, 8, 21, tzinfo=UTC),
    )
    assert first == second

    changed = [dict(row) for row in picks]
    changed[0]["player_id"] = "different"
    with pytest.raises(ValueError, match="payload changed"):
        archive_sleeper_draft(
            tmp_path,
            draft=draft,
            picks=changed,
            traded_picks=[],
        )


def test_archive_hash_tampering_is_detected(tmp_path) -> None:
    archive_sleeper_draft(tmp_path, draft=_draft(), picks=_picks(), traded_picks=[])
    path = tmp_path / "2025" / "draft-1" / "picks.json"
    path.write_text(json.dumps([{"tampered": True}]), encoding="utf-8")

    with pytest.raises(ValueError, match="integrity failure"):
        load_archived_draft(path.parent)


def test_archive_normalization_preserves_outcomes_without_market_values(tmp_path) -> None:
    archive_sleeper_draft(
        tmp_path,
        draft=_draft(),
        picks=_picks(),
        traded_picks=[],
        retrieved_at=datetime(2025, 8, 20, tzinfo=UTC),
    )
    frame, report = normalize_archive(tmp_path)

    assert len(frame) == 4
    assert list(frame["actual_pick"]) == [1, 2, 3, 4]
    assert set(frame["scoring"]) == {"ppr"}
    assert set(frame["teams"]) == {4}
    assert set(frame["qb_slots_per_team"]) == {1}
    assert set(frame["starter_slots_per_team"]) == {7}
    assert "market_adp" not in frame.columns
    assert report["drafts"] == 1
    assert report["picks"] == 4


def _market_snapshot(captured_at: datetime, *, rank_shift: float = 0.0) -> pd.DataFrame:
    raw = pd.DataFrame(
        [
            {"player_name": "Alpha Runner", "position": "RB", "nfl_team": "ARI", "rank": 10 + rank_shift, "rank_std": 2.0},
            {"player_name": "Bravo Target", "position": "WR", "nfl_team": "BUF", "rank": 20 + rank_shift, "rank_std": 3.0},
            {"player_name": "Charlie Passer", "position": "QB", "nfl_team": "CIN", "rank": 30 + rank_shift, "rank_std": 4.0},
            {"player_name": "Delta Tight", "position": "TE", "nfl_team": "DAL", "rank": 40 + rank_shift, "rank_std": 5.0},
        ]
    )
    return normalize_ranking_frame(
        raw,
        source="fantasypros_adp",
        source_kind="market",
        ranking_type="adp",
        scoring="ppr",
        captured_at_utc=captured_at,
        source_url="https://example.test/adp",
    )


def test_market_asof_join_uses_latest_pre_draft_snapshot_not_future_snapshot() -> None:
    start = datetime(2025, 8, 15, 18, tzinfo=UTC)
    drafts = normalize_sleeper_draft(_draft(start=start), _picks(), retrieved_at=start.isoformat())
    older = _market_snapshot(start - timedelta(days=10), rank_shift=100)
    latest_prior = _market_snapshot(start - timedelta(hours=2), rank_shift=0)
    future = _market_snapshot(start + timedelta(hours=1), rank_shift=-100)
    rankings = pd.concat([older, latest_prior, future], ignore_index=True)

    joined, report = asof_join_market_snapshots(
        drafts,
        rankings,
        source="fantasypros_adp",
    )

    assert list(joined["market_adp"]) == [10.0, 20.0, 30.0, 40.0]
    assert joined["point_in_time_market_verified"].all()
    assert (joined["market_snapshot_at"] < joined["draft_started_at"]).all()
    assert report["matched_rows"] == 4
    assert report["verified_rate"] == 1.0


def test_market_asof_join_leaves_missing_snapshot_unmatched() -> None:
    start = datetime(2025, 8, 15, 18, tzinfo=UTC)
    drafts = normalize_sleeper_draft(_draft(start=start), _picks(), retrieved_at=start.isoformat())
    rankings = _market_snapshot(start + timedelta(days=1))

    joined, report = asof_join_market_snapshots(
        drafts,
        rankings,
        source="fantasypros_adp",
    )

    assert joined["market_adp"].isna().all()
    assert not joined["point_in_time_market_verified"].any()
    assert report["drafts_without_pre_draft_snapshot"] == 1
    assert report["missing_market_is_never_imputed_from_actual_pick"] is True


def test_market_asof_join_fails_closed_on_ambiguous_identity() -> None:
    start = datetime(2025, 8, 15, 18, tzinfo=UTC)
    drafts = normalize_sleeper_draft(_draft(start=start), _picks(), retrieved_at=start.isoformat())
    rankings = _market_snapshot(start - timedelta(hours=2))
    duplicate = rankings.iloc[[0]].copy()
    rankings = pd.concat([rankings, duplicate], ignore_index=True)

    joined, report = asof_join_market_snapshots(
        drafts,
        rankings,
        source="fantasypros_adp",
    )

    alpha = joined.loc[joined["player_name"].eq("Alpha Runner")].iloc[0]
    assert pd.isna(alpha["market_adp"])
    assert alpha["market_identity_match_method"] == "ambiguous_name_position_team"
    assert report["ambiguous_identity_rows"] == 1
