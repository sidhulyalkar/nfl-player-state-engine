from __future__ import annotations

import json

import pandas as pd

from player_state_engine.api.draft_reliability_routes import capture_draft_decision_checkpoint
from player_state_engine.fantasy.draft import DraftState
from player_state_engine.fantasy.draft_qualification import DraftQualificationReport
from player_state_engine.fantasy.league import LeagueConfig


def _board() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": "RB1",
                "player_name": "Runner One",
                "position": "RB",
                "live_rank": 1,
                "guarded_draft_action": "DRAFT",
                "live_draft_score": 118.0,
                "room_challenger_score": 115.0,
                "survival_to_next_pick": 0.18,
                "room_survival_to_next_pick": 0.16,
                "draft_reliability_score": 91.0,
                "draft_reliability_reasons": "fresh inputs and strong league value",
            },
            {
                "player_id": "WR1",
                "player_name": "Receiver One",
                "position": "WR",
                "live_rank": 2,
                "guarded_draft_action": "CONSIDER",
                "live_draft_score": 112.0,
                "room_challenger_score": 113.0,
                "survival_to_next_pick": 0.42,
                "room_survival_to_next_pick": 0.39,
                "draft_reliability_score": 86.0,
                "draft_reliability_reasons": "good value with more waitability",
            },
        ]
    )


def _state() -> DraftState:
    return DraftState(
        teams=8,
        draft_slot=4,
        current_pick=12,
        total_rounds=18,
        drafted_player_ids=("QB1", "RB0", "WR0"),
        roster_player_ids=("QB1",),
    )


def _league() -> LeagueConfig:
    return LeagueConfig(
        teams=8,
        scoring="ppr",
        roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3, "BENCH": 6},
    )


def _qualification(*, blocked: bool = False) -> DraftQualificationReport:
    blockers = ("STALE_PROJECTIONS",) if blocked else ()
    return DraftQualificationReport(
        status="BLOCKED" if blocked else "READY",
        can_act=not blocked,
        blocking_reasons=blockers,
        caution_reasons=(),
        league_inputs_ready=True,
        projection_fresh=not blocked,
        live_snapshot_fresh=True,
        refresh_healthy=True,
        readiness_score=94.0,
        projection_age_hours=48.0 if blocked else 2.0,
        max_projection_age_hours=24.0,
        snapshot_age_seconds=8.0,
        stale_after_seconds=60.0,
    )


def test_checkpoint_records_exact_state_once(tmp_path) -> None:
    path = tmp_path / "draft_decisions.jsonl"
    first = capture_draft_decision_checkpoint(
        _board(),
        _state(),
        _league(),
        league_key="league-8ppr",
        audit_path=path,
        qualification=_qualification(),
        trust={"artifact_sha256": "projection-hash"},
        survival_model={"source": "normal_adp"},
        room_simulations=600,
    )
    second = capture_draft_decision_checkpoint(
        _board(),
        _state(),
        _league(),
        league_key="league-8ppr",
        audit_path=path,
        qualification=_qualification(),
        trust={"artifact_sha256": "projection-hash"},
        survival_model={"source": "normal_adp"},
        room_simulations=600,
    )

    assert first["status"] == "RECORDED"
    assert first["written"] is True
    assert second["status"] == "DEDUPLICATED"
    assert second["written"] is False
    assert first["decision_id"] == second["decision_id"]

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["recommendation_player_id"] == "RB1"
    assert record["context"]["current_pick"] == 12
    assert record["model_metadata"]["qualification"]["status"] == "READY"
    assert record["model_metadata"]["trust"]["artifact_sha256"] == "projection-hash"
    assert record["model_metadata"]["research"]["room_challenger_promoted"] is False


def test_blocked_state_is_preserved_as_non_actionable_evidence(tmp_path) -> None:
    path = tmp_path / "blocked.jsonl"
    result = capture_draft_decision_checkpoint(
        _board(),
        _state(),
        _league(),
        league_key="league-8ppr",
        audit_path=path,
        qualification=_qualification(blocked=True),
        trust={"artifact_sha256": "stale-projection-hash"},
        survival_model={"source": "normal_adp"},
        room_simulations=600,
    )

    assert result["status"] == "RECORDED"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["model_metadata"]["qualification"]["can_act"] is False
    assert record["model_metadata"]["qualification"]["blocking_reasons"] == [
        "STALE_PROJECTIONS"
    ]
