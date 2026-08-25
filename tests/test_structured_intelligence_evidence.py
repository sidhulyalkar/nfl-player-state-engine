from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from player_state_engine.evaluation.ablations import AblationRun
from player_state_engine.evaluation.benchmark import BenchmarkResult
from player_state_engine.evaluation.intelligence_evidence import (
    base_feature_columns,
    build_incremental_feature_sets,
    evaluate_incremental_intelligence_evidence,
)
from player_state_engine.state_graph.experiments import EvidenceTier

TARGET = "fantasy_points_ppr"


def _fake_run(name: str, error: float, rows: pd.DataFrame) -> AblationRun:
    predictions = rows[["season", "week", "player_id", "position"]].copy()
    actual = np.full(len(rows), 10.0)
    median = actual + error
    predictions[f"{TARGET}_q10"] = median - 5.0
    predictions[f"{TARGET}_q50"] = median
    predictions[f"{TARGET}_q90"] = median + 5.0
    predictions["actual"] = actual
    predictions["method"] = "quantile_engine"
    empty = pd.DataFrame()
    result = BenchmarkResult(
        predictions=predictions,
        fold_metrics=empty,
        summary_metrics=empty,
        season_metrics=empty,
        position_metrics=empty,
        quantile_calibration=empty,
        interval_calibration=empty,
    )
    return AblationRun(name=name, feature_count=1, result=result)


def _evaluation_frame(*, include_coverage: bool = True) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    positions = ("QB", "RB", "WR", "TE")
    for season in (2024, 2025):
        for week in range(1, 11):
            for position in positions:
                for player_number in range(5):
                    rows.append(
                        {
                            "season": season,
                            "week": week,
                            "player_id": f"{position}-{player_number}",
                            "position": position,
                            "base_numeric": float(player_number),
                            "availability_expected_active": 0.9,
                            "official_structured_snapshot_found": 1,
                            "official_structured_max_conflict": 0.0,
                            "opportunity_target_share_roll3_mean": 0.2,
                            "news_structured_snapshot_found": 1,
                            "news_structured_starter_security_signal": 0.5,
                            "news_structured_max_conflict": 0.0,
                            "persona_training_focus": 0.4,
                            "persona_snapshot_found": 1,
                            "news_structured_research_only": 1,
                            "news_structured_as_of_utc": "2025-01-01T00:00:00Z",
                        }
                    )
    frame = pd.DataFrame(rows)
    if include_coverage:
        for family in (
            "official_availability",
            "objective_opportunity",
            "structured_news",
            "public_player_context",
        ):
            frame[f"{family}_source_covered"] = 1
    return frame


def _runs(frame: pd.DataFrame) -> dict[str, AblationRun]:
    errors = {
        "numerical_baseline": 3.0,
        "official_availability": 2.0,
        "objective_reference": 1.5,
        "structured_news": 0.8,
        "public_player_context": 0.5,
        "official_availability_shuffled_control": 2.8,
        "objective_opportunity_shuffled_control": 2.4,
        "structured_news_shuffled_control": 1.4,
        "public_player_context_shuffled_control": 1.0,
        "official_availability_shifted_time_leakage_control": 1.8,
        "objective_opportunity_shifted_time_leakage_control": 1.2,
        "structured_news_shifted_time_leakage_control": 0.4,
        "public_player_context_shifted_time_leakage_control": 0.2,
    }
    return {name: _fake_run(name, error, frame) for name, error in errors.items()}


def _evaluate(
    frame: pd.DataFrame,
    *,
    evidence_tier: EvidenceTier = EvidenceTier.SYNTHETIC_ONLY,
) -> pd.DataFrame:
    return evaluate_incremental_intelligence_evidence(
        frame,
        _runs(frame),
        TARGET,
        evidence_tier=evidence_tier,
        bootstrap_samples=400,
        minimum_position_rows=50,
        minimum_paired_rows=250,
        minimum_seasons=2,
        minimum_blocks=8,
    )


def test_incremental_feature_hierarchy_excludes_audit_coverage_and_raw_outcomes() -> None:
    frame = _evaluation_frame()
    frame["opportunity_target_share"] = 0.99
    supplied = [
        "base_numeric",
        "official_availability_source_covered",
        "news_structured_research_only",
        "news_structured_as_of_utc",
        "availability_expected_active",
        "opportunity_target_share_roll3_mean",
        "news_structured_starter_security_signal",
        "persona_training_focus",
    ]
    base = base_feature_columns(supplied)
    variants = build_incremental_feature_sets(supplied, frame)

    assert base == ["base_numeric"]
    assert "availability_expected_active" in variants["official_availability"]
    assert "opportunity_target_share_roll3_mean" in variants["objective_reference"]
    assert "opportunity_target_share" not in variants["objective_reference"]
    assert "news_structured_starter_security_signal" in variants["structured_news"]
    assert "persona_training_focus" in variants["public_player_context"]
    assert not any(column.endswith("_source_covered") for column in variants["public_player_context"])
    assert "news_structured_research_only" not in variants["structured_news"]
    assert "news_structured_as_of_utc" not in variants["structured_news"]


def test_strong_synthetic_evidence_can_clear_model_gate_but_not_activation_review() -> None:
    evidence = _evaluate(_evaluation_frame(include_coverage=True))

    assert set(evidence["family"]) == {
        "official_availability",
        "objective_opportunity",
        "structured_news",
        "public_player_context",
    }
    assert (evidence["effect"] > 0.0).all()
    assert (evidence["ci_low"] > 0.0).all()
    assert (evidence["p_value"] > 0.0).all()
    assert (evidence["fdr_q_value"] <= 0.10).all()
    assert evidence["identity_control_passed"].all()
    assert (evidence["source_coverage"] == 1.0).all()
    assert (evidence["source_coverage_measurement_rate"] == 1.0).all()
    assert evidence["model_gate_passed"].all()
    assert (~evidence["eligible_for_activation_review"]).all()
    assert (evidence["evidence_tier"] == int(EvidenceTier.SYNTHETIC_ONLY)).all()
    assert all(
        "evidence_tier_below_activation_review" in blockers
        for blockers in evidence["activation_review_blockers"]
    )
    assert (evidence["authority"] == "research_evidence_only").all()
    assert (~evidence["automatic_promotion"]).all()
    assert (~evidence["production_projection_changed"]).all()


def test_explicit_tier_two_evidence_can_clear_activation_review_mechanics() -> None:
    evidence = _evaluate(
        _evaluation_frame(include_coverage=True),
        evidence_tier=EvidenceTier.MULTI_SEASON_ISOLATED,
    )

    assert evidence["model_gate_passed"].all()
    assert evidence["eligible_for_activation_review"].all()
    assert (evidence["evidence_tier"] == int(EvidenceTier.MULTI_SEASON_ISOLATED)).all()
    assert evidence["activation_review_blockers"].map(len).eq(0).all()


def test_missing_source_coverage_blocks_tier_two_review_even_with_model_lift() -> None:
    evidence = _evaluate(
        _evaluation_frame(include_coverage=False),
        evidence_tier=EvidenceTier.MULTI_SEASON_ISOLATED,
    )

    assert evidence["model_gate_passed"].all()
    assert (~evidence["eligible_for_activation_review"]).all()
    assert evidence["source_coverage"].isna().all()
    assert all(
        "source_coverage_not_measured" in blockers
        for blockers in evidence["activation_review_blockers"]
    )


def test_partial_source_coverage_measurement_fails_closed() -> None:
    frame = _evaluation_frame(include_coverage=True)
    frame.loc[frame.index[0], "official_availability_source_covered"] = np.nan
    evidence = _evaluate(frame, evidence_tier=EvidenceTier.MULTI_SEASON_ISOLATED)
    official = evidence.loc[evidence["family"].eq("official_availability")].iloc[0]

    assert float(official["source_coverage_measurement_rate"]) < 1.0
    assert "source_coverage_incomplete" in official["activation_review_blockers"]
    assert not bool(official["eligible_for_activation_review"])


def test_conflicting_source_coverage_aliases_are_rejected() -> None:
    frame = _evaluation_frame(include_coverage=True)
    frame["official_structured_source_covered"] = 0

    with pytest.raises(ValueError, match="Conflicting official_availability source coverage aliases"):
        _evaluate(frame, evidence_tier=EvidenceTier.MULTI_SEASON_ISOLATED)


def test_invalid_source_coverage_value_is_rejected() -> None:
    frame = _evaluation_frame(include_coverage=True)
    frame.loc[frame.index[0], "structured_news_source_covered"] = "probably"

    with pytest.raises(ValueError, match="unrecognized binary values"):
        _evaluate(frame, evidence_tier=EvidenceTier.MULTI_SEASON_ISOLATED)
