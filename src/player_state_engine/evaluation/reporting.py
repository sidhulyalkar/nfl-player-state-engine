from __future__ import annotations

from pathlib import Path

from player_state_engine.data.io import write_table
from player_state_engine.evaluation.benchmark import BenchmarkResult, write_benchmark_markdown


def persist_benchmark(
    result: BenchmarkResult, target: str, output_dir: str | Path
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "predictions": write_table(result.predictions, output_dir / f"{target}_predictions.csv"),
        "fold_metrics": write_table(result.fold_metrics, output_dir / f"{target}_fold_metrics.csv"),
        "summary_metrics": write_table(
            result.summary_metrics, output_dir / f"{target}_summary_metrics.csv"
        ),
        "season_metrics": write_table(
            result.season_metrics, output_dir / f"{target}_season_metrics.csv"
        ),
        "position_metrics": write_table(
            result.position_metrics, output_dir / f"{target}_position_metrics.csv"
        ),
        "quantile_calibration": write_table(
            result.quantile_calibration, output_dir / f"{target}_quantile_calibration.csv"
        ),
        "interval_calibration": write_table(
            result.interval_calibration, output_dir / f"{target}_interval_calibration.csv"
        ),
        "report": write_benchmark_markdown(
            result, target, output_dir / f"{target}_benchmark_report.md"
        ),
    }
