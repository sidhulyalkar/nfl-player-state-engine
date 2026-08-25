from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from player_state_engine.fantasy.draft_market_archive import (
    asof_join_market_snapshots,
    normalize_sleeper_draft,
)
from player_state_engine.fantasy.draft_market_processed import resolve_processed_player_identity
from player_state_engine.fantasy.rankings import normalize_ranking_frame
from scripts.build_draft_survival_observations import build_observations


def _draft(start: datetime) -> dict[str, object]:
    return {
        "draft_id": "pipeline-draft",
        "league_id": "pipeline-league",
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
        },
        "metadata": {"scoring_type": "ppr"},
    }


def _picks() -> list[dict[str, object]]:
    positions = ("RB", "WR", "QB", "TE")
    rows: list[dict[str, object]] = []
    for pick in range(1, 13):
        position = positions[(pick - 1) % len(positions)]
        rows.append(
            {
                "draft_id": "pipeline-draft",
                "player_id": f"sleeper-{pick:02d}",
                "pick_no": pick,
                "round": (pick - 1) // 4 + 1,
                "draft_slot": (pick - 1) % 4 + 1,
                "picked_by": f"user-{(pick - 1) % 4 + 1}",
                "roster_id": str((pick - 1) % 4 + 1),
                "metadata": {
                    "first_name": f"Player{pick:02d}",
                    "last_name": "Test",
                    "position": position,
                    "team": "ARI",
                },
            }
        )
    return rows


def _rankings(captured_at: datetime) -> pd.DataFrame:
    positions = ("RB", "WR", "QB", "TE")
    raw = pd.DataFrame(
        [
            {
                "player_name": f"Player{pick:02d} Test",
                "position": positions[(pick - 1) % len(positions)],
                "nfl_team": "ARI",
                "rank": float(pick),
                "rank_std": 3.0,
            }
            for pick in range(1, 13)
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


def test_archive_market_join_feeds_survival_observation_contract() -> None:
    start = datetime(2025, 8, 15, 18, tzinfo=UTC)
    outcomes = normalize_sleeper_draft(
        _draft(start),
        _picks(),
        retrieved_at=(start + timedelta(days=1)).isoformat(),
    )
    outcomes = resolve_processed_player_identity(outcomes)
    joined, report = asof_join_market_snapshots(
        outcomes,
        _rankings(start - timedelta(hours=4)),
        source="fantasypros_adp",
    )
    observations = build_observations(joined, default_teams=4)

    assert report["verified_rate"] == 1.0
    assert joined["player_id"].notna().all()
    assert joined["market_adp"].notna().all()
    assert joined["point_in_time_market_verified"].all()
    assert not observations.empty
    assert observations["player_id"].notna().all()
    assert observations["point_in_time_market_verified"].all()
    assert (observations["market_snapshot_age_hours"] == 4.0).all()
    assert {
        "survived_to_next_pick",
        "position_market_rank",
        "position_supply_to_next",
        "position_supply_next_round",
        "draft_market_depth",
    }.issubset(observations.columns)
