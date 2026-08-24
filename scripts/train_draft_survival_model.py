from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pandas as pd

from player_state_engine.fantasy.draft_market import train_chronological_survival_model


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha() -> str | None:
    if os.getenv("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Train the empirical survival-to-next-pick challenger using strict chronological "
            "draft-room holdouts and point-in-time market evidence."
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
    parser.add_argument("--test-fraction", type=float, default=0.20)
    parser.add_argument("--min-holdout-drafts", type=int, default=5)
    parser.add_argument("--min-brier-improvement", type=float, default=0.001)
    parser.add_argument("--max-ece-regression", type=float, default=0.02)
    parser.add_argument("--min-format-rows", type=int, default=50)
    parser.add_argument("--max-format-brier-regression", type=float, default=0.005)
    parser.add_argument(
        "--allow-unverified-market",
        action="store_true",
        help=(
            "Allow an artifact to clear the market-provenance gate when archived ADP timestamps "
            "are incomplete. This is intended for research only; strict operation leaves it off."
        ),
    )
    args = parser.parse_args()

    observations = _read_table(args.observations)
    result = train_chronological_survival_model(
        observations,
        min_rows=args.min_rows,
        min_drafts=args.min_drafts,
        test_fraction=args.test_fraction,
        min_holdout_drafts=args.min_holdout_drafts,
        min_brier_improvement=args.min_brier_improvement,
        max_ece_regression=args.max_ece_regression,
        min_format_rows=args.min_format_rows,
        max_format_brier_regression=args.max_format_brier_regression,
        require_verified_market=not args.allow_unverified_market,
    )

    artifact = result.artifact
    artifact.save(args.output)
    payload = dict(result.report)
    payload.update(
        {
            "trained_at": artifact.trained_at,
            "artifact_promoted": artifact.promoted,
            "artifact_promotion_reason": artifact.promotion_reason,
            "observations": {
                "path": str(args.observations),
                "bytes": args.observations.stat().st_size,
                "sha256": _sha256(args.observations),
            },
            "model": {
                "path": str(args.output),
                "bytes": args.output.stat().st_size,
                "sha256": _sha256(args.output),
            },
            "git_sha": _git_sha(),
        }
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
