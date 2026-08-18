from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.fantasy.draft_survival import train_survival_model


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Train the empirical survival-to-next-pick model from point-in-time "
            "historical draft observations."
        )
    )
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/models/draft_survival/draft_survival.joblib"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("artifacts/models/draft_survival/metrics.json"),
    )
    parser.add_argument("--min-rows", type=int, default=250)
    parser.add_argument("--min-drafts", type=int, default=5)
    parser.add_argument("--min-brier-improvement", type=float, default=0.001)
    args = parser.parse_args()

    observations = _read_table(args.observations)
    artifact = train_survival_model(
        observations,
        min_rows=args.min_rows,
        min_drafts=args.min_drafts,
        min_brier_improvement=args.min_brier_improvement,
    )
    artifact.save(args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": artifact.version,
        "trained_at": artifact.trained_at,
        "rows": artifact.rows,
        "drafts": artifact.drafts,
        "metrics": artifact.metrics,
        "promoted": artifact.promoted,
        "promotion_reason": artifact.promotion_reason,
        "observations": str(args.observations),
        "model": str(args.output),
    }
    args.report.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
