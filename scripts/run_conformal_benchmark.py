from __future__ import annotations

import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd

from player_state_engine.config import load_config
from player_state_engine.pipelines.workflows import calibrate_predictions_workflow

TARGETS = (
    "passing_yards",
    "targets",
    "receptions",
    "fantasy_points_ppr",
    "receiving_yards",
    "rushing_yards",
    "carries",
)


def main() -> None:
    cfg = load_config("configs/base.yaml")
    root = Path("artifacts/reports")
    output = root / "conformal_real"
    rows: list[dict[str, float | str]] = []
    for target in TARGETS:
        source = root / "benchmark_real" / target / f"{target}_predictions.csv"
        if not source.exists():
            raise FileNotFoundError(f"Missing frozen benchmark predictions: {source}")
        paths = calibrate_predictions_workflow(source, target, output / target, cfg)
        summary = pd.read_csv(paths["summary"])
        raw = summary.loc[summary["method"] == "quantile_engine"].iloc[0]
        calibrated = summary.loc[summary["method"] == "quantile_engine_conformal"].iloc[0]
        rows.append(
            {
                "target": target,
                "raw_pinball": float(raw["mean_pinball"]),
                "calibrated_pinball": float(calibrated["mean_pinball"]),
                "raw_coverage": float(raw["interval_coverage"]),
                "calibrated_coverage": float(calibrated["interval_coverage"]),
                "raw_mae": float(raw["mae"]),
                "calibrated_mae": float(calibrated["mae"]),
            }
        )
    master = pd.DataFrame(rows)
    master["pinball_improvement_pct"] = 100.0 * (
        master["raw_pinball"] - master["calibrated_pinball"]
    ) / master["raw_pinball"]
    master["raw_coverage_error"] = (master["raw_coverage"] - 0.8).abs()
    master["calibrated_coverage_error"] = (master["calibrated_coverage"] - 0.8).abs()
    output.mkdir(parents=True, exist_ok=True)
    master.to_csv(output / "conformal_master_summary.csv", index=False)
    print(master.to_string(index=False))


if __name__ == "__main__":
    main()
