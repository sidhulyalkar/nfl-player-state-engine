from __future__ import annotations

import sys

import argparse
import hashlib
import json
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd

from player_state_engine.config import EngineConfig, load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.benchmark import run_multiseason_benchmark
from player_state_engine.evaluation.metrics import evaluate_quantiles
from player_state_engine.evaluation.reporting import persist_benchmark
from player_state_engine.features.weekly import (
    SKILL_POSITIONS,
    build_weekly_features,
    feature_columns_for_target,
)
from player_state_engine.models.position_quantile import PositionSpecificQuantileBundle
from player_state_engine.models.quantile import TARGET_POSITIONS

PLAYER_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.csv"
)
SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
DEFAULT_TARGETS = (
    "fantasy_points_ppr",
    "targets",
    "carries",
    "receptions",
    "receiving_yards",
    "rushing_yards",
    "passing_yards",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, path: Path, *, force: bool = False) -> Path:
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "NFLPlayerStateEngine/0.3"})
    with urllib.request.urlopen(request, timeout=90) as response, path.open("wb") as output:  # noqa: S310
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    return path


def acquire_sources(
    seasons: tuple[int, ...], raw_dir: Path, manifest_path: Path, *, force: bool = False
) -> dict[str, Path]:
    sources: dict[str, Path] = {}
    entries: list[dict[str, object]] = []
    for season in seasons:
        url = PLAYER_URL.format(season=season)
        path = download(url, raw_dir / f"stats_player_week_{season}.csv", force=force)
        sources[f"player_stats_{season}"] = path
        entries.append(
            {
                "name": f"player_stats_{season}",
                "url": url,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    schedule_path = download(SCHEDULE_URL, raw_dir / "games.csv", force=force)
    sources["schedules"] = schedule_path
    entries.append(
        {
            "name": "schedules",
            "url": SCHEDULE_URL,
            "path": str(schedule_path),
            "bytes": schedule_path.stat().st_size,
            "sha256": sha256_file(schedule_path),
        }
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "seasons": seasons,
                "sources": entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return sources


def load_regular_season_inputs(sources: dict[str, Path], seasons: tuple[int, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    stats = pd.concat(
        [pd.read_csv(sources[f"player_stats_{season}"], low_memory=False) for season in seasons],
        ignore_index=True,
    )
    stats = stats.loc[
        stats["season_type"].eq("REG") & stats["position"].isin(SKILL_POSITIONS)
    ].copy()
    schedules = pd.read_csv(sources["schedules"], low_memory=False)
    schedules = schedules.loc[
        schedules["season"].isin(seasons) & schedules["game_type"].eq("REG")
    ].copy()
    return stats, schedules


def _position_specific_carries(
    frame: pd.DataFrame,
    features: list[str],
    cfg: EngineConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    target = "carries"
    data = frame.loc[frame["player_history_count"] >= 1].copy()
    data = data.loc[data["position"].isin(TARGET_POSITIONS[target])].dropna(subset=[target])
    data["fold_week"] = data["season"] * 25 + data["week"]
    weeks = sorted(data["fold_week"].unique())
    parts: list[pd.DataFrame] = []
    model: PositionSpecificQuantileBundle | None = None
    for fold_index, test_week in enumerate(weeks[cfg.benchmark.min_train_weeks :]):
        train = data.loc[data["fold_week"] < test_week]
        test = data.loc[data["fold_week"] == test_week].copy()
        if model is None or fold_index % cfg.benchmark.retrain_every_weeks == 0:
            model = PositionSpecificQuantileBundle(replace(cfg.model, targets=(target,))).fit(
                train,
                features,
                target,
                min_rows_per_position=50,
            )
        predicted = model.predict(test)
        predicted["actual"] = test[target].to_numpy(dtype=float)
        predicted["method"] = "position_specific_quantile"
        predicted["fold_week"] = int(test_week)
        parts.append(predicted)
    predictions = pd.concat(parts, ignore_index=True)
    summary = pd.DataFrame(
        [
            {
                "method": "position_specific_quantile",
                "rows": len(predictions),
                **evaluate_quantiles(
                    predictions["actual"], predictions, target, cfg.model.quantiles
                ),
            }
        ]
    )
    position_rows: list[dict[str, object]] = []
    for position, subset in predictions.groupby("position"):
        position_rows.append(
            {
                "method": "position_specific_quantile",
                "position": position,
                "rows": len(subset),
                **evaluate_quantiles(subset["actual"], subset, target, cfg.model.quantiles),
            }
        )
    return predictions, summary, pd.DataFrame(position_rows)


def _build_master_report(results: dict[str, object], output_dir: Path) -> dict[str, Path]:
    summary_frames: list[pd.DataFrame] = []
    season_frames: list[pd.DataFrame] = []
    position_frames: list[pd.DataFrame] = []
    calibration_frames: list[pd.DataFrame] = []
    comparison_rows: list[dict[str, object]] = []
    season_win_rows: list[dict[str, object]] = []
    position_win_rows: list[dict[str, object]] = []

    for target, result in results.items():
        summary = result.summary_metrics.copy()  # type: ignore[attr-defined]
        summary["target"] = target
        summary_frames.append(summary)
        season = result.season_metrics.copy()  # type: ignore[attr-defined]
        season["target"] = target
        season_frames.append(season)
        position = result.position_metrics.copy()  # type: ignore[attr-defined]
        position["target"] = target
        position_frames.append(position)
        calibration = result.quantile_calibration.copy()  # type: ignore[attr-defined]
        calibration["target"] = target
        calibration_frames.append(calibration)

        engine = summary.loc[summary["method"] == "quantile_engine"].iloc[0]
        baseline = summary.loc[summary["method"] != "quantile_engine"].sort_values("mean_pinball").iloc[0]
        comparison_rows.append(
            {
                "target": target,
                "best_baseline": baseline["method"],
                "engine_mae": engine["mae"],
                "baseline_mae": baseline["mae"],
                "mae_improvement_pct": 100 * (baseline["mae"] - engine["mae"]) / baseline["mae"],
                "engine_mean_pinball": engine["mean_pinball"],
                "baseline_mean_pinball": baseline["mean_pinball"],
                "pinball_improvement_pct": 100
                * (baseline["mean_pinball"] - engine["mean_pinball"])
                / baseline["mean_pinball"],
                "engine_coverage": engine["interval_coverage"],
                "coverage_error_abs": abs(engine["interval_coverage"] - 0.8),
                "verdict": "win" if engine["mean_pinball"] < baseline["mean_pinball"] else "loss",
            }
        )
        wins = 0
        for heldout_season, subset in season.groupby("season"):
            engine_season = subset.loc[subset["method"] == "quantile_engine"].iloc[0]
            baseline_season = subset.loc[subset["method"] != "quantile_engine"].sort_values("mean_pinball").iloc[0]
            wins += int(engine_season["mean_pinball"] < baseline_season["mean_pinball"])
        season_win_rows.append(
            {"target": target, "winning_seasons": wins, "evaluated_seasons": season["season"].nunique()}
        )
        for position_name, subset in position.groupby("position"):
            engine_position = subset.loc[subset["method"] == "quantile_engine"].iloc[0]
            baseline_position = subset.loc[subset["method"] != "quantile_engine"].sort_values("mean_pinball").iloc[0]
            position_win_rows.append(
                {
                    "target": target,
                    "position": position_name,
                    "engine_mean_pinball": engine_position["mean_pinball"],
                    "best_baseline": baseline_position["method"],
                    "baseline_mean_pinball": baseline_position["mean_pinball"],
                    "improvement_pct": 100
                    * (baseline_position["mean_pinball"] - engine_position["mean_pinball"])
                    / baseline_position["mean_pinball"],
                    "engine_wins": bool(engine_position["mean_pinball"] < baseline_position["mean_pinball"]),
                }
            )

    paths = {
        "master_summary": write_table(pd.concat(summary_frames, ignore_index=True), output_dir / "benchmark_master_summary.csv"),
        "season_metrics": write_table(pd.concat(season_frames, ignore_index=True), output_dir / "benchmark_season_metrics.csv"),
        "position_metrics": write_table(pd.concat(position_frames, ignore_index=True), output_dir / "benchmark_position_metrics.csv"),
        "quantile_calibration": write_table(pd.concat(calibration_frames, ignore_index=True), output_dir / "benchmark_quantile_calibration_all.csv"),
        "engine_vs_baseline": write_table(pd.DataFrame(comparison_rows), output_dir / "benchmark_engine_vs_best_baseline.csv"),
        "season_wins": write_table(pd.DataFrame(season_win_rows), output_dir / "benchmark_season_wins.csv"),
        "position_wins": write_table(pd.DataFrame(position_win_rows), output_dir / "benchmark_position_wins.csv"),
    }
    return paths


def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    seasons = tuple(args.seasons or cfg.seasons)
    raw_dir = Path(args.raw_dir)
    output_dir = Path(args.output_dir)
    manifest_path = output_dir / "DATA_MANIFEST.json"
    sources = acquire_sources(seasons, raw_dir, manifest_path, force=args.force_download)
    if args.download_only:
        print(manifest_path)
        return

    feature_path = Path(args.features)
    if args.reuse_features and feature_path.exists():
        features = read_table(feature_path)
    else:
        stats, schedules = load_regular_season_inputs(sources, seasons)
        features = build_weekly_features(stats, schedules, cfg.features)
        write_table(features, feature_path)
    if args.features_only:
        print(feature_path)
        return

    results: dict[str, object] = {}
    for target in args.targets or DEFAULT_TARGETS:
        columns = feature_columns_for_target(features, target)
        result = run_multiseason_benchmark(
            features,
            columns,
            target,
            replace(cfg.model, targets=(target,)),
            min_train_weeks=cfg.benchmark.min_train_weeks,
            retrain_every_weeks=cfg.benchmark.retrain_every_weeks,
            rolling_window=cfg.benchmark.rolling_window,
            engine_strategy="pooled",
        )
        persist_benchmark(result, target, output_dir / target)
        results[target] = result
        if target == "carries" and not args.skip_position_correction:
            corrected_predictions, corrected_summary, corrected_positions = _position_specific_carries(
                features, columns, cfg
            )
            write_table(
                corrected_predictions,
                output_dir / target / "carries_position_specific_predictions.csv",
            )
            write_table(
                corrected_summary,
                output_dir / target / "carries_position_specific_summary.csv",
            )
            write_table(
                corrected_positions,
                output_dir / target / "carries_position_specific_position_metrics.csv",
            )
    _build_master_report(results, output_dir)
    print(f"Benchmark complete: {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reproduce the real 2020–2025 nflverse benchmark.")
    parser.add_argument("--config", default="configs/benchmark_real.yaml")
    parser.add_argument("--raw-dir", default="data/raw/nflverse")
    parser.add_argument("--features", default="data/processed/weekly_features_2020_2025.parquet")
    parser.add_argument("--output-dir", default="artifacts/reports/benchmark_real")
    parser.add_argument("--seasons", nargs="+", type=int)
    parser.add_argument("--targets", nargs="+")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--features-only", action="store_true")
    parser.add_argument("--reuse-features", action="store_true")
    parser.add_argument("--skip-position-correction", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
