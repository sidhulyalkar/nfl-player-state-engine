from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from player_state_engine.fantasy.decision_audit import (
    append_decision_record,
    build_draft_audit_record,
    load_decision_records,
    settle_draft_decision_regret,
)
from player_state_engine.fantasy.draft import DraftState
from player_state_engine.fantasy.league import LeagueConfig


def _board() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": "A",
                "player_name": "Alpha",
                "position": "WR",
                "live_rank": 1,
                "draft_action": "DRAFT NOW",
                "guarded_draft_action": "TARGET",
                "live_draft_score": 88.0,
                "room_challenger_score": 84.0,
                "survival_to_next_pick": 0.20,
                "room_survival_to_next_pick": 0.27,
                "draft_reliability_score": 64.0,
                "draft_reliability_reasons": "room disagreement",
            },
            {
                "player_id": "B",
                "player_name": "Beta",
                "position": "RB",
                "live_rank": 2,
                "draft_action": "TARGET",
                "guarded_draft_action": "TARGET",
                "live_draft_score": 85.0,
                "room_challenger_score": 86.0,
                "survival_to_next_pick": 0.35,
                "room_survival_to_next_pick": 0.30,
                "draft_reliability_score": 80.0,
                "draft_reliability_reasons": "models agree",
            },
        ]
    )


def _state() -> DraftState:
    return DraftState(
        teams=8,
        draft_slot=3,
        current_pick=11,
        total_rounds=18,
        drafted_player_ids=("X", "Y"),
        roster_player_ids=("X",),
    )


def test_draft_audit_id_is_stable_for_same_information_state() -> None:
    config = LeagueConfig(teams=8, roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3})
    first = build_draft_audit_record(
        _board(),
        _state(),
        config,
        league_key="league-1",
        recorded_at=datetime(2026, 8, 20, 18, 0, tzinfo=UTC),
    )
    second = build_draft_audit_record(
        _board(),
        _state(),
        config,
        league_key="league-1",
        recorded_at=datetime(2026, 8, 20, 18, 1, tzinfo=UTC),
    )
    assert first.decision_id == second.decision_id
    assert first.recommendation_player_id == "A"
    assert first.recommendation_action == "TARGET"


def test_append_decision_record_deduplicates_refreshes(tmp_path) -> None:
    record = build_draft_audit_record(
        _board(),
        _state(),
        LeagueConfig(teams=8),
        league_key="league-1",
    )
    path = tmp_path / "draft.jsonl"
    assert append_decision_record(path, record)
    assert not append_decision_record(path, record)
    loaded = load_decision_records(path)
    assert len(loaded) == 1
    assert loaded[0]["decision_id"] == record.decision_id


def test_regret_is_settled_only_against_visible_candidates() -> None:
    record = build_draft_audit_record(
        _board(),
        _state(),
        LeagueConfig(teams=8),
        league_key="league-1",
    )
    outcomes = pd.DataFrame(
        {
            "player_id": ["A", "B", "C"],
            "realized_value": [20.0, 27.0, 100.0],
        }
    )
    settled = settle_draft_decision_regret([record.as_dict()], outcomes)
    assert float(settled.iloc[0]["decision_regret"]) == 7.0
    assert settled.iloc[0]["best_visible_player_id"] == "B"
