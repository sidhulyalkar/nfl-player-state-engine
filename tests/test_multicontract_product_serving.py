from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.draft_actionability import assess_candidate_scope_actionability
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.projection_contracts import select_projection_scoring_contract
from player_state_engine.fantasy.readiness import assess_league_readiness
from player_state_engine.fantasy.valuation import value_players


def _league(scoring: str) -> LeagueConfig:
    return LeagueConfig(
        teams=1,
        scoring=scoring,
        roster_slots={"WR": 1},
        replacement_buffer=0,
        replacement_buffer_fraction=0.0,
        risk_preference=1.0,
    )


def _contract_rows(
    config: LeagueConfig,
    *,
    policy: str,
    scale: float,
) -> list[dict[str, object]]:
    values = {
        "safe": (80.0, 150.0, 170.0),
        "volatile": (20.0, 150.0, 260.0),
        "replacement": (60.0, 100.0, 140.0),
    }
    rows: list[dict[str, object]] = []
    for index, (player_id, (q10, q50, q90)) in enumerate(values.items(), start=1):
        rows.append(
            {
                "scoring_contract_id": config.scoring_contract_id,
                "player_id": player_id,
                "player_name": player_id.title(),
                "position": "WR",
                "season_points_q10": q10,
                "season_points_q50": q50,
                "season_points_q90": q90,
                "league_season_points_q10": q10 * scale,
                "league_season_points_q50": q50 * scale,
                "league_season_points_q90": q90 * scale,
                "league_scoring_exact": True,
                "decision_quantile_policy": policy,
                "market_adp": float(index),
                "model_version": "0.17.0-test",
            }
        )
    return rows


def _shared_artifact() -> tuple[pd.DataFrame, LeagueConfig, LeagueConfig]:
    ppr = _league("ppr")
    half = _league("half_ppr")
    frame = pd.DataFrame(
        _contract_rows(ppr, policy="qualified_distribution", scale=1.0)
        + _contract_rows(half, policy="q50_only", scale=0.8)
    )
    return frame, ppr, half


def test_shared_artifact_selects_exact_scoring_contract_before_valuation() -> None:
    frame, ppr, half = _shared_artifact()

    ppr_values = value_players(frame, ppr).set_index("player_id")
    half_values = value_players(frame, half).set_index("player_id")

    assert len(ppr_values) == 3
    assert len(half_values) == 3
    assert set(ppr_values["scoring_contract_id"]) == {ppr.scoring_contract_id}
    assert set(half_values["scoring_contract_id"]) == {half.scoring_contract_id}
    assert ppr_values.loc["safe", "valuation_points_q50"] == 150.0
    assert half_values.loc["safe", "valuation_points_q50"] == 120.0


def test_readiness_and_actionability_do_not_misclassify_cross_contract_rows_as_duplicates() -> None:
    frame, _, half = _shared_artifact()
    readiness = assess_league_readiness(frame, half)
    board = build_decision_board(frame, half, DecisionType.DRAFT)
    actionability = assess_candidate_scope_actionability(
        frame,
        board.head(2),
        half,
        global_readiness=readiness,
    )

    assert readiness.ready is True
    assert readiness.projection_rows == 3
    assert readiness.unique_player_coverage == 1.0
    assert "DUPLICATE_PLAYER_IDS" not in readiness.flags
    assert actionability.actionable is True
    assert "DUPLICATE_CANDIDATE_PROJECTION_ROWS" not in actionability.blocking_reasons
    assert actionability.exact_scoring_coverage == 1.0


def test_missing_requested_contract_fails_closed() -> None:
    frame, _, _ = _shared_artifact()
    standard = _league("standard")

    with pytest.raises(ValueError, match="does not contain the requested scoring contract"):
        select_projection_scoring_contract(frame, standard)
    with pytest.raises(ValueError, match="does not contain the requested scoring contract"):
        value_players(frame, standard)


def test_duplicate_player_inside_one_contract_fails_closed() -> None:
    frame, ppr, _ = _shared_artifact()
    duplicate = pd.concat(
        [frame, frame.loc[frame["scoring_contract_id"].eq(ppr.scoring_contract_id)].iloc[[0]]],
        ignore_index=True,
    )

    with pytest.raises(ValueError, match="duplicate player_id rows"):
        select_projection_scoring_contract(duplicate, ppr)


def test_q50_only_authority_applies_to_trade_stash_and_dynasty_scores() -> None:
    frame, _, half = _shared_artifact()

    for decision in (DecisionType.TRADE, DecisionType.STASH, DecisionType.DYNASTY):
        board = build_decision_board(frame, half, decision).set_index("player_id")
        assert board.loc["safe", "decision_specific_score"] == pytest.approx(
            board.loc["volatile", "decision_specific_score"]
        )
        assert bool(board.loc["safe", "decision_tail_authorized"]) is False
        assert bool(board.loc["volatile", "decision_tail_authorized"]) is False
        assert "wide outcome range" not in str(board.loc["volatile", "decision_reasons"])


def test_legacy_single_contract_artifact_remains_readable_for_development() -> None:
    frame, ppr, _ = _shared_artifact()
    legacy = frame.loc[frame["scoring_contract_id"].eq(ppr.scoring_contract_id)].drop(
        columns=["scoring_contract_id"]
    )

    selected = select_projection_scoring_contract(legacy, ppr)
    assert len(selected) == 3
    assert "scoring_contract_id" not in selected

    with pytest.raises(ValueError, match="does not declare scoring_contract_id"):
        select_projection_scoring_contract(legacy, ppr, require_explicit_contract=True)
