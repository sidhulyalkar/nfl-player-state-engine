from pathlib import Path

import pandas as pd

from player_state_engine.product.research import ResearchArtifacts, team_context_response


def _write_research_artifacts(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    benchmark = root / "benchmark"
    conformal = root / "conformal"
    opportunity = root / "opportunity"
    historical_sources = root / "historical_sources"
    target = benchmark / "fantasy_points_ppr"
    target.mkdir(parents=True)
    conformal.mkdir()
    opportunity.mkdir()
    historical_sources.mkdir()
    pd.DataFrame(
        [{"target": "fantasy_points_ppr", "engine_mean_pinball": 1.4, "verdict": "win"}]
    ).to_csv(benchmark / "benchmark_engine_vs_best_baseline.csv", index=False)
    pd.DataFrame([{"target": "fantasy_points_ppr", "calibrated_coverage": 0.82}]).to_csv(
        conformal / "conformal_master_summary.csv", index=False
    )
    pd.DataFrame([{"method": "numerical_baseline", "mean_pinball": 1.38}]).to_csv(
        opportunity / "frozen_opportunity_summary.csv", index=False
    )
    predictions = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 18,
                "player_id": "qb-b",
                "player_name": "QB B",
                "position": "QB",
                "method": "quantile_engine",
                "fantasy_points_ppr_q10": 10.0,
                "fantasy_points_ppr_q50": 20.0,
                "fantasy_points_ppr_q90": 30.0,
                "actual": 22.0,
            },
            {
                "season": 2025,
                "week": 18,
                "player_id": "rb-a",
                "player_name": "RB A",
                "position": "RB",
                "method": "quantile_engine",
                "fantasy_points_ppr_q10": 11.0,
                "fantasy_points_ppr_q50": 25.0,
                "fantasy_points_ppr_q90": 34.0,
                "actual": 19.0,
            },
            {
                "season": 2025,
                "week": 18,
                "player_id": "qb-a",
                "player_name": "QB A",
                "position": "QB",
                "method": "quantile_engine",
                "fantasy_points_ppr_q10": 9.0,
                "fantasy_points_ppr_q50": 20.0,
                "fantasy_points_ppr_q90": 31.0,
                "actual": 24.0,
            },
            {
                "season": 2025,
                "week": 18,
                "player_id": "ignored",
                "player_name": "Baseline",
                "position": "QB",
                "method": "rolling_5",
                "fantasy_points_ppr_q10": 1.0,
                "fantasy_points_ppr_q50": 2.0,
                "fantasy_points_ppr_q90": 3.0,
                "actual": 4.0,
            },
        ]
    )
    predictions.to_csv(target / "fantasy_points_ppr_predictions.csv", index=False)
    frozen = predictions.iloc[:1].rename(
        columns={
            "actual": "actual_fantasy_points_ppr",
            "fantasy_points_ppr_q10": "adjusted_q10",
            "fantasy_points_ppr_q50": "adjusted_q50",
            "fantasy_points_ppr_q90": "adjusted_q90",
        }
    )
    frozen["method"] = "numerical_baseline"
    frozen.to_csv(opportunity / "frozen_opportunity_predictions.csv", index=False)
    pd.DataFrame(
        [
            {
                "method": "snap_counts",
                "mean_pinball": 1.41,
                "pinball_improvement_vs_baseline_pct": -2.1,
            }
        ]
    ).to_csv(historical_sources / "historical_source_summary.csv", index=False)
    pd.DataFrame(
        [
            {
                "source_family": "snap_counts",
                "season": 2025,
                "source_status": "available",
                "explicit_evidence_match_rate": 0.99,
                "id_resolution_rate": 0.98,
            }
        ]
    ).to_csv(
        historical_sources / "historical_source_source_coverage.csv",
        index=False,
    )

    team_context = root / "team_context.parquet"
    pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 2,
                "recent_team": "AAA",
                "team_plays_actual": 99.0,
                "team_plays_lag1": 60.0,
                "team_plays_roll4": 58.0,
                "team_neutral_pass_rate_roll4": 0.7,
                "team_target_hhi_roll4": 0.3,
                "team_carry_hhi_roll4": 0.4,
            },
            {
                "season": 2025,
                "week": 2,
                "recent_team": "BBB",
                "team_plays_actual": 1.0,
                "team_plays_lag1": 55.0,
                "team_plays_roll4": 52.0,
                "team_neutral_pass_rate_roll4": 0.5,
                "team_target_hhi_roll4": 0.2,
                "team_carry_hhi_roll4": 0.3,
            },
        ]
    ).to_parquet(team_context, index=False)
    return benchmark, conformal, opportunity, historical_sources, team_context


def test_research_summary_reports_provenance_and_missing_artifacts(tmp_path: Path) -> None:
    benchmark, conformal, opportunity, historical_sources, _ = _write_research_artifacts(tmp_path)
    repository = ResearchArtifacts(
        benchmark_root=benchmark,
        conformal_root=conformal,
        opportunity_root=opportunity,
        historical_source_root=historical_sources,
    )
    summary = repository.summary()
    assert summary["data_mode"] == "RESEARCH"
    assert summary["missing_inputs"] == []
    assert summary["artifacts"]["benchmark"]["available"] is True
    assert summary["artifacts"]["benchmark"]["row_count"] == 1
    assert summary["artifacts"]["benchmark"]["file_modified_at"]
    assert "updated_at" not in summary["artifacts"]["benchmark"]
    assert summary["artifact_file_modified_at"]
    assert summary["benchmark"][0]["verdict"] == "win"
    assert summary["historical_sources"][0]["method"] == "snap_counts"
    assert summary["historical_source_coverage"][0]["id_resolution_rate"] == 0.98

    missing = ResearchArtifacts(
        benchmark_root=tmp_path / "no-benchmark",
        conformal_root=conformal,
        opportunity_root=opportunity,
        historical_source_root=historical_sources,
    ).summary()
    assert missing["missing_inputs"] == ["benchmark"]
    assert missing["benchmark"] == []


def test_historical_predictions_are_filtered_normalized_and_ranked(tmp_path: Path) -> None:
    benchmark, conformal, opportunity, historical_sources, _ = _write_research_artifacts(tmp_path)
    repository = ResearchArtifacts(
        benchmark_root=benchmark,
        conformal_root=conformal,
        opportunity_root=opportunity,
        historical_source_root=historical_sources,
    )
    response = repository.predictions(season=2025, week=18, position="QB", limit=10)
    assert response["data_mode"] == "HISTORICAL_BACKTEST"
    assert response["total_matches"] == 2
    assert [row["player_id"] for row in response["predictions"]] == ["qb-a", "qb-b"]
    assert [row["overall_rank"] for row in response["predictions"]] == [2, 3]
    assert [row["position_rank"] for row in response["predictions"]] == [1, 2]
    assert response["predictions"][0]["q50"] == 20.0

    frozen = repository.predictions(source="frozen_opportunity", season=2025, week=18, limit=10)
    assert frozen["filters"]["method"] == "numerical_baseline"
    assert frozen["predictions"][0]["q50"] == 20.0


def test_team_context_exposes_only_pregame_fields_and_metric_ranks(tmp_path: Path) -> None:
    _, _, _, _, team_context = _write_research_artifacts(tmp_path)
    response = team_context_response(team_context, season=2025, week=2)
    assert response["data_mode"] == "HISTORICAL_BACKTEST"
    assert response["total_matches"] == 2
    assert response["artifact"]["excluded_columns"] == "*_actual same-week outcomes"
    assert all("team_plays_actual" not in row for row in response["teams"])
    assert response["teams"][0]["play_volume_rank"] == 1.0

    filtered = team_context_response(team_context, season=2025, week=2, team="BBB")
    assert filtered["total_matches"] == 1
    assert filtered["teams"][0]["play_volume_rank"] == 2.0
