from __future__ import annotations

import sys

import shutil
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from player_state_engine.config import load_config
from player_state_engine.data.synthetic import write_synthetic_dataset
from player_state_engine.pipelines.workflows import (
    build_features_workflow,
    train_opportunity_workflow,
)


def main() -> None:
    root = Path(".smoke_opportunity")
    if root.exists():
        shutil.rmtree(root)
    write_synthetic_dataset(root / "raw", seasons=(2022, 2023, 2024), weeks_per_season=8, seed=44)
    config = load_config("configs/base.yaml")
    config.model = replace(config.model, max_iter=15, min_samples_leaf=8, max_leaf_nodes=7)
    features = build_features_workflow(
        root / "raw" / "player_stats.csv",
        root / "raw" / "schedules.csv",
        root / "features.csv",
        config,
    )
    paths = train_opportunity_workflow(
        features,
        root / "opportunity.joblib",
        root / "predictions.csv",
        config,
        holdout_season=2024,
    )
    print(paths)


if __name__ == "__main__":
    main()
