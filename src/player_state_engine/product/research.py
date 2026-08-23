from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.product.provenance import artifact_metadata, frame_records

ResearchPredictionSource = Literal["benchmark", "frozen_opportunity"]


@lru_cache(maxsize=16)
def _read_cached(path: str, modified_ns: int) -> pd.DataFrame:
    del modified_ns  # It is part of the cache key and intentionally invalidates refreshed files.
    return read_table(path)


def _read_artifact(path: Path) -> pd.DataFrame:
    return _read_cached(str(path.resolve()), path.stat().st_mtime_ns).copy()


def _pinball(actual: np.ndarray, prediction: np.ndarray, quantile: float) -> float:
    residual = actual - prediction
    loss = np.maximum(quantile * residual, (quantile - 1.0) * residual)
    return float(np.mean(loss))


def _diagnostic_row(data: pd.DataFrame, **labels: object) -> dict[str, object]:
    clean = data.dropna(subset=["actual", "q10", "q50", "q90"]).copy()
    if clean.empty:
        return {**labels, "rows": 0}
    actual = pd.to_numeric(clean["actual"], errors="coerce").to_numpy(dtype=float)
    q10 = pd.to_numeric(clean["q10"], errors="coerce").to_numpy(dtype=float)
    q50 = pd.to_numeric(clean["q50"], errors="coerce").to_numpy(dtype=float)
    q90 = pd.to_numeric(clean["q90"], errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(actual) & np.isfinite(q10) & np.isfinite(q50) & np.isfinite(q90)
    actual, q10, q50, q90 = actual[finite], q10[finite], q50[finite], q90[finite]
    if not len(actual):
        return {**labels, "rows": 0}
    crossed = (q10 > q50) | (q50 > q90)
    ordered = np.sort(np.column_stack([q10, q50, q90]), axis=1)
    q10, q50, q90 = ordered[:, 0], ordered[:, 1], ordered[:, 2]
    coverage = float(np.mean((actual >= q10) & (actual <= q90)))
    interval_width = q90 - q10
    median_error = q50 - actual
    alpha = 0.20
    interval_score = interval_width.copy()
    below = actual < q10
    above = actual > q90
    interval_score[below] += (2.0 / alpha) * (q10[below] - actual[below])
    interval_score[above] += (2.0 / alpha) * (actual[above] - q90[above])
    coverage_gap = coverage - 0.80
    if abs(coverage_gap) <= 0.03:
        calibration_status = "ON_TARGET"
    elif coverage_gap < -0.03:
        calibration_status = "UNDERCOVERED"
    else:
        calibration_status = "OVERWIDE"
    return {
        **labels,
        "rows": int(len(actual)),
        "empirical_80_coverage": coverage,
        "coverage_gap": coverage_gap,
        "calibration_status": calibration_status,
        "q50_mae": float(np.mean(np.abs(median_error))),
        "median_bias": float(np.mean(median_error)),
        "mean_interval_width": float(np.mean(interval_width)),
        "lower_miss_rate": float(np.mean(actual < q10)),
        "upper_miss_rate": float(np.mean(actual > q90)),
        "pinball_q10": _pinball(actual, q10, 0.10),
        "pinball_q50": _pinball(actual, q50, 0.50),
        "pinball_q90": _pinball(actual, q90, 0.90),
        "mean_pinball": float(
            np.mean(
                [
                    _pinball(actual, q10, 0.10),
                    _pinball(actual, q50, 0.50),
                    _pinball(actual, q90, 0.90),
                ]
            )
        ),
        "mean_interval_score_80": float(np.mean(interval_score)),
        "crossed_quantile_rate_before_repair": float(np.mean(crossed)),
    }


class ResearchArtifacts:
    """Read-only adapter over frozen research artifacts used by the product API."""

    def __init__(
        self,
        *,
        benchmark_root: str | Path = "artifacts/reports/benchmark_real",
        conformal_root: str | Path = "artifacts/reports/conformal_real",
        opportunity_root: str | Path = "artifacts/reports/opportunity_ablation_real",
        historical_source_root: str
        | Path = "artifacts/reports/historical_source_ablation_hardened",
    ) -> None:
        self.benchmark_root = Path(benchmark_root)
        self.conformal_root = Path(conformal_root)
        self.opportunity_root = Path(opportunity_root)
        self.historical_source_root = Path(historical_source_root)

    def summary(self) -> dict[str, object]:
        paths = {
            "benchmark": self.benchmark_root / "benchmark_engine_vs_best_baseline.csv",
            "conformal": self.conformal_root / "conformal_master_summary.csv",
            "frozen_opportunity": self.opportunity_root / "frozen_opportunity_summary.csv",
            "historical_sources": (self.historical_source_root / "historical_source_summary.csv"),
            "historical_source_coverage": (
                self.historical_source_root / "historical_source_source_coverage.csv"
            ),
        }
        frames = {
            name: _read_artifact(path) if path.is_file() else pd.DataFrame()
            for name, path in paths.items()
        }
        artifacts = {
            name: artifact_metadata(path, row_count=(len(frames[name]) if path.is_file() else None))
            for name, path in paths.items()
        }
        updated = [
            str(metadata["file_modified_at"])
            for metadata in artifacts.values()
            if metadata["file_modified_at"] is not None
        ]
        missing = [name for name, metadata in artifacts.items() if not metadata["available"]]
        return {
            "data_mode": "RESEARCH",
            "artifact_file_modified_at": max(updated) if updated else None,
            "missing_inputs": missing,
            "artifacts": artifacts,
            "benchmark": frame_records(frames["benchmark"]),
            "conformal": frame_records(frames["conformal"]),
            "frozen_opportunity": frame_records(frames["frozen_opportunity"]),
            "historical_sources": frame_records(frames["historical_sources"]),
            "historical_source_coverage": frame_records(frames["historical_source_coverage"]),
        }

    def _prediction_frame(
        self,
        *,
        source: ResearchPredictionSource,
        target: str,
        method: str | None,
    ) -> tuple[pd.DataFrame, Path, str, list[str], str]:
        if source == "benchmark":
            if not target.replace("_", "").isalnum():
                raise ValueError("target may contain only letters, numbers, and underscores")
            path = self.benchmark_root / target / f"{target}_predictions.csv"
            q_columns = [f"{target}_q10", f"{target}_q50", f"{target}_q90"]
            actual_column = "actual"
            selected_method = method or "quantile_engine"
        elif source == "frozen_opportunity":
            path = self.opportunity_root / "frozen_opportunity_predictions.csv"
            q_columns = ["adjusted_q10", "adjusted_q50", "adjusted_q90"]
            actual_column = "actual_fantasy_points_ppr"
            selected_method = method or "numerical_baseline"
        else:
            raise ValueError(f"Unsupported prediction source: {source}")

        if not path.is_file():
            raise FileNotFoundError(f"Research prediction artifact unavailable: {path}")
        data = _read_artifact(path)
        required = {"season", "week", "player_id", "position", "method", *q_columns}
        missing_columns = sorted(required - set(data.columns))
        if missing_columns:
            raise ValueError(f"Prediction artifact missing columns: {missing_columns}")
        data = data.loc[data["method"].astype(str).eq(selected_method)].copy()
        data["q10"] = pd.to_numeric(data[q_columns[0]], errors="coerce")
        data["q50"] = pd.to_numeric(data[q_columns[1]], errors="coerce")
        data["q90"] = pd.to_numeric(data[q_columns[2]], errors="coerce")
        data["actual"] = (
            pd.to_numeric(data[actual_column], errors="coerce") if actual_column in data else np.nan
        )
        return data, path, actual_column, q_columns, selected_method

    def predictions(
        self,
        *,
        source: ResearchPredictionSource = "benchmark",
        target: str = "fantasy_points_ppr",
        season: int | None = None,
        week: int | None = None,
        position: str | None = None,
        player_id: str | None = None,
        method: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        data, path, actual_column, _q_columns, selected_method = self._prediction_frame(
            source=source,
            target=target,
            method=method,
        )
        artifact_rows = len(data)
        if season is not None:
            data = data.loc[pd.to_numeric(data["season"], errors="coerce").eq(season)]
        if week is not None:
            data = data.loc[pd.to_numeric(data["week"], errors="coerce").eq(week)]
        data = _add_historical_ranks(data)

        if position:
            data = data.loc[data["position"].astype(str).str.upper().eq(position.upper())]
        if player_id:
            data = data.loc[data["player_id"].astype(str).eq(str(player_id))]
        data = data.sort_values(
            ["season", "week", "overall_rank"],
            ascending=[False, False, True],
            kind="mergesort",
        )
        total_matches = len(data)
        data = data.head(limit)
        metadata = artifact_metadata(path, row_count=artifact_rows)
        metadata["source"] = source
        metadata["target"] = target
        return {
            "data_mode": "HISTORICAL_BACKTEST",
            "artifact": metadata,
            "filters": {
                "source": source,
                "target": target,
                "season": season,
                "week": week,
                "position": position.upper() if position else None,
                "player_id": player_id,
                "method": selected_method,
                "limit": limit,
            },
            "total_matches": total_matches,
            "returned": len(data),
            "missing_inputs": ([] if actual_column in data.columns else ["actual"]),
            "predictions": frame_records(data),
        }

    def diagnostics(
        self,
        *,
        target: str = "fantasy_points_ppr",
        method: str = "quantile_engine",
        minimum_rows: int = 20,
    ) -> dict[str, object]:
        """Summarize frozen out-of-sample calibration without changing model authority."""

        data, path, actual_column, _q_columns, selected_method = self._prediction_frame(
            source="benchmark",
            target=target,
            method=method,
        )
        if actual_column not in data.columns:
            raise ValueError(f"Prediction artifact missing actual outcome column: {actual_column}")
        overall = _diagnostic_row(data, scope="overall")
        by_position = [
            _diagnostic_row(group, scope="position", position=str(position))
            for position, group in data.groupby(data["position"].astype(str).str.upper(), sort=True)
            if len(group) >= minimum_rows
        ]
        by_season = [
            _diagnostic_row(group, scope="season", season=int(season))
            for season, group in data.groupby(pd.to_numeric(data["season"], errors="coerce"), sort=True)
            if pd.notna(season) and len(group) >= minimum_rows
        ]
        by_position_season = [
            _diagnostic_row(
                group,
                scope="position_season",
                position=str(position).upper(),
                season=int(season),
            )
            for (position, season), group in data.groupby(
                [data["position"].astype(str).str.upper(), pd.to_numeric(data["season"], errors="coerce")],
                sort=True,
            )
            if pd.notna(season) and len(group) >= minimum_rows
        ]
        return {
            "data_mode": "HISTORICAL_BACKTEST",
            "authority": "diagnostic_only",
            "target_coverage": 0.80,
            "method": selected_method,
            "target": target,
            "minimum_rows": int(minimum_rows),
            "artifact": artifact_metadata(path, row_count=len(data)),
            "overall": overall,
            "by_position": by_position,
            "by_season": by_season,
            "by_position_season": by_position_season,
        }


def team_context_response(
    path: str | Path,
    *,
    season: int | None = None,
    week: int | None = None,
    team: str | None = None,
    limit: int = 1000,
) -> dict[str, object]:
    candidate = Path(path)
    if not candidate.is_file():
        raise FileNotFoundError(f"Team-context artifact unavailable: {candidate}")
    data = _read_artifact(candidate)
    required = {"season", "week", "recent_team"}
    missing_columns = sorted(required - set(data.columns))
    if missing_columns:
        raise ValueError(f"Team-context artifact missing columns: {missing_columns}")

    artifact_rows = len(data)
    expected_features = {
        "team_plays_roll4",
        "team_neutral_pass_rate_roll4",
        "team_target_hhi_roll4",
        "team_carry_hhi_roll4",
    }
    missing_features = sorted(expected_features - set(data.columns))
    safe_columns = [
        column
        for column in data.columns
        if column in required or column.endswith("_lag1") or column.endswith("_roll4")
    ]
    data = data.loc[:, safe_columns].copy()
    if season is not None:
        data = data.loc[pd.to_numeric(data["season"], errors="coerce").eq(season)]
    if week is not None:
        data = data.loc[pd.to_numeric(data["week"], errors="coerce").eq(week)]
    data = _add_team_context_ranks(data)
    if team:
        data = data.loc[data["recent_team"].astype(str).str.upper().eq(team.upper())]
    data = data.sort_values(["season", "week", "recent_team"], ascending=[False, False, True])
    total_matches = len(data)
    data = data.head(limit)
    return {
        "data_mode": "HISTORICAL_BACKTEST",
        "artifact": {
            **artifact_metadata(candidate, row_count=artifact_rows),
            "cutoff": "lagged features available before the listed week",
            "excluded_columns": "*_actual same-week outcomes",
        },
        "filters": {
            "season": season,
            "week": week,
            "team": team.upper() if team else None,
            "limit": limit,
        },
        "total_matches": total_matches,
        "returned": len(data),
        "missing_inputs": missing_features,
        "teams": frame_records(data),
    }


def _add_historical_ranks(data: pd.DataFrame) -> pd.DataFrame:
    ranked = data.sort_values(
        ["season", "week", "q50", "player_id"],
        ascending=[True, True, False, True],
        kind="mergesort",
    ).copy()
    ranked["overall_rank"] = ranked.groupby(["season", "week"], sort=False).cumcount() + 1
    ranked["position_rank"] = (
        ranked.groupby(["season", "week", "position"], sort=False).cumcount() + 1
    )
    return ranked


def _add_team_context_ranks(data: pd.DataFrame) -> pd.DataFrame:
    metrics = {
        "team_plays_roll4": "play_volume_rank",
        "team_neutral_pass_rate_roll4": "neutral_pass_rate_rank",
        "team_target_hhi_roll4": "target_concentration_rank",
        "team_carry_hhi_roll4": "carry_concentration_rank",
    }
    for metric, rank_name in metrics.items():
        if metric in data:
            data[rank_name] = data.groupby(["season", "week"])[metric].rank(
                method="min", ascending=False, na_option="keep"
            )
    return data
