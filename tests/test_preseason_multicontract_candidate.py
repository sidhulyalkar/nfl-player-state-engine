from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.preseason_league_score import LEAGUE_SCORE_TARGET
from player_state_engine.models.conformal import TargetPositionConformalCalibrator
from player_state_engine.product.preseason_multicontract_candidate import (
    PPR_POLICY,
    Q50_POLICY,
    ContractEvidence,
    build_contract_product_frame,
    combine_contract_product_frames,
    market_context_from_nfl_hub,
    validate_release_evidence,
)

NOW = datetime(2026, 8, 30, 20, 0, tzinfo=UTC)


def _config(scoring: str) -> LeagueConfig:
    return LeagueConfig(teams=1, scoring=scoring, roster_slots={"WR": 1})


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2026,
                "player_id": "p1",
                "player_name": "Player One",
                "position": "WR",
                "recent_team": "AAA",
                "age_at_season_start": 24.5,
                "rookie": 0,
                "experience_seasons_prior": 3,
                "roster_status": "ACTIVE",
            },
            {
                "season": 2026,
                "player_id": "p2",
                "player_name": "Player Two",
                "position": "WR",
                "recent_team": "BBB",
                "age_at_season_start": 22.0,
                "rookie": 1,
                "experience_seasons_prior": 0,
                "roster_status": "ACTIVE",
            },
        ]
    )


def _predictions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": "p1",
                "player_name": "Player One",
                "position": "WR",
                "recent_team": "AAA",
                f"{LEAGUE_SCORE_TARGET}_q10": 80.0,
                f"{LEAGUE_SCORE_TARGET}_q50": 150.0,
                f"{LEAGUE_SCORE_TARGET}_q90": 220.0,
            },
            {
                "player_id": "p2",
                "player_name": "Player Two",
                "position": "WR",
                "recent_team": "BBB",
                f"{LEAGUE_SCORE_TARGET}_q10": 60.0,
                f"{LEAGUE_SCORE_TARGET}_q50": 120.0,
                f"{LEAGUE_SCORE_TARGET}_q90": 190.0,
            },
        ]
    )


def _evidence(config: LeagueConfig, policy: str) -> ContractEvidence:
    return ContractEvidence(
        slug="league",
        scoring_contract_id=config.scoring_contract_id,
        direct_gate_approved=True,
        uncertainty_gate_approved=policy == PPR_POLICY,
        decision_quantile_policy=policy,
    )


def _identity_calibrator() -> TargetPositionConformalCalibrator:
    calibrator = TargetPositionConformalCalibrator()
    for quantile in (0.1, 0.5, 0.9):
        calibrator.target_fallbacks[(LEAGUE_SCORE_TARGET, quantile)] = 0.0
        calibrator.target_scale_fallbacks[(LEAGUE_SCORE_TARGET, quantile)] = 1.0
    calibrator.fitted_through_season = 2025
    return calibrator


def test_q50_only_contract_preserves_raw_direct_scores_and_rejects_calibrator() -> None:
    half = _config("half_ppr")
    frame = build_contract_product_frame(
        _predictions(),
        _features(),
        half,
        _evidence(half, Q50_POLICY),
        source_cutoff_utc=NOW,
    )

    assert set(frame["decision_quantile_policy"]) == {Q50_POLICY}
    assert not frame["decision_tail_authorized"].any()
    assert frame["league_scoring_exact"].all()
    assert frame["league_season_points_q50"].tolist() == [150.0, 120.0]
    assert frame["raw_league_season_points_q90"].tolist() == [220.0, 190.0]

    with pytest.raises(ValueError, match="must not apply"):
        build_contract_product_frame(
            _predictions(),
            _features(),
            half,
            _evidence(half, Q50_POLICY),
            source_cutoff_utc=NOW,
            calibrator=_identity_calibrator(),
        )


def test_qualified_ppr_contract_requires_reviewed_calibrator() -> None:
    ppr = _config("ppr")
    with pytest.raises(ValueError, match="requires the reviewed calibrator"):
        build_contract_product_frame(
            _predictions(),
            _features(),
            ppr,
            _evidence(ppr, PPR_POLICY),
            source_cutoff_utc=NOW,
        )

    frame = build_contract_product_frame(
        _predictions(),
        _features(),
        ppr,
        _evidence(ppr, PPR_POLICY),
        source_cutoff_utc=NOW,
        calibrator=_identity_calibrator(),
    )
    assert frame["decision_tail_authorized"].all()
    assert set(frame["uncertainty_authority"]) == {"earlier_season_conformal_qualified"}
    assert frame["league_season_points_q50"].tolist() == [150.0, 120.0]


def test_market_context_requires_observational_hub_authority() -> None:
    snapshot = {
        "authority": "observational_nfl_state_only",
        "players": [
            {"player_id": "p1", "market_rank": 5, "market_adp": 5.5},
            {"player_id": "p2", "market_rank": 17, "market_adp": 18.0},
        ],
    }
    market = market_context_from_nfl_hub(snapshot).set_index("player_id")
    assert market.loc["p1", "market_adp"] == 5.5

    with pytest.raises(ValueError, match="invalid authority"):
        market_context_from_nfl_hub({**snapshot, "authority": "model_predictions"})


def test_combined_contract_artifact_requires_same_player_universe() -> None:
    ppr = _config("ppr")
    half = _config("half_ppr")
    ppr_frame = build_contract_product_frame(
        _predictions(),
        _features(),
        ppr,
        _evidence(ppr, PPR_POLICY),
        source_cutoff_utc=NOW,
        calibrator=_identity_calibrator(),
    )
    half_frame = build_contract_product_frame(
        _predictions(),
        _features(),
        half,
        _evidence(half, Q50_POLICY),
        source_cutoff_utc=NOW,
    )
    combined = combine_contract_product_frames({"ppr": ppr_frame, "half": half_frame})
    assert len(combined) == 4
    assert not combined.duplicated(["scoring_contract_id", "player_id"]).any()

    with pytest.raises(ValueError, match="player universes differ"):
        combine_contract_product_frames({"ppr": ppr_frame, "half": half_frame.iloc[[0]].copy()})


def test_release_evidence_requires_frozen_ppr_pass_half_fail(tmp_path: Path) -> None:
    ppr = _config("ppr")
    half = _config("half_ppr")
    leagues = {
        "8_team_ppr_2qb_expanded": ppr,
        "12_team_half_ppr_median": half,
    }
    direct = {
        "authority": "direct_league_score_research_only",
        "automatic_promotion": False,
        "leagues": {
            slug: {"gate": {"approved": True, "blockers": []}}
            for slug in leagues
        },
    }
    uncertainty = {
        "authority": "direct_league_score_uncertainty_research_only",
        "automatic_promotion": False,
        "leagues": {
            "8_team_ppr_2qb_expanded": {"decision": {"approved": True, "blockers": []}},
            "12_team_half_ppr_median": {
                "decision": {"approved": False, "blockers": ["POSITION_INTERVAL_COVERAGE:TE"]}
            },
        },
    }
    direct_path = tmp_path / "direct.json"
    uncertainty_path = tmp_path / "uncertainty.json"
    direct_path.write_text(json.dumps(direct), encoding="utf-8")
    uncertainty_path.write_text(json.dumps(uncertainty), encoding="utf-8")

    evidence = validate_release_evidence(direct_path, uncertainty_path, leagues)
    assert evidence["8_team_ppr_2qb_expanded"].decision_quantile_policy == PPR_POLICY
    assert evidence["12_team_half_ppr_median"].decision_quantile_policy == Q50_POLICY

    uncertainty["leagues"]["12_team_half_ppr_median"]["decision"]["approved"] = True
    uncertainty_path.write_text(json.dumps(uncertainty), encoding="utf-8")
    with pytest.raises(ValueError, match="verdict changed"):
        validate_release_evidence(direct_path, uncertainty_path, leagues)
