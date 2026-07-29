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

    def predictions(
        self,
        *,
        source: ResearchPredictionSource = "benchmark",
        target: str = "fantasy_points_ppr",
        season: int | None = None,
        week: int | None = None,
        position: str | None = None,
        method: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
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
        artifact_rows = len(data)
        required = {"season", "week", "player_id", "position", "method", *q_columns}
        missing_columns = sorted(required - set(data.columns))
        if missing_columns:
            raise ValueError(f"Prediction artifact missing columns: {missing_columns}")

        data = data.loc[data["method"].astype(str).eq(selected_method)].copy()
        if season is not None:
            data = data.loc[pd.to_numeric(data["season"], errors="coerce").eq(season)]
        if week is not None:
            data = data.loc[pd.to_numeric(data["week"], errors="coerce").eq(week)]

        data["q10"] = pd.to_numeric(data[q_columns[0]], errors="coerce")
        data["q50"] = pd.to_numeric(data[q_columns[1]], errors="coerce")
        data["q90"] = pd.to_numeric(data[q_columns[2]], errors="coerce")
        data["actual"] = (
            pd.to_numeric(data[actual_column], errors="coerce") if actual_column in data else np.nan
        )
        data = _add_historical_ranks(data)

        if position:
            data = data.loc[data["position"].astype(str).str.upper().eq(position.upper())]
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
                "method": selected_method,
                "limit": limit,
            },
            "total_matches": total_matches,
            "returned": len(data),
            "missing_inputs": ([] if actual_column in data.columns else ["actual"]),
            "predictions": frame_records(data),
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
