from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.data.nflverse import download_nflverse
from player_state_engine.fantasy.preseason import (
    build_current_preseason_features,
    build_preseason_season_dataset,
)
from player_state_engine.product.nfl_hub import _to_pandas
from player_state_engine.product.preseason_candidate import (
    build_preseason_product_frame,
    fit_preseason_candidate,
    register_candidate_bundle,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize an immutable, non-promoting 2026 preseason skill-player candidate. "
            "This command cannot create or move a production champion pointer."
        )
    )
    parser.add_argument("--config", default="configs/base.yaml")
    parser.add_argument("--history-seasons", nargs="+", type=int, default=list(range(2015, 2026)))
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/preseason_2026_candidate"))
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--registry-root", type=Path, required=True)
    parser.add_argument("--benchmark-git-sha", required=True)
    parser.add_argument("--benchmark-artifact-digest", required=True)
    parser.add_argument("--benchmark-approved", action="store_true")
    args = parser.parse_args()

    if not args.benchmark_approved:
        raise RuntimeError("A reviewed, approved frozen preseason benchmark is required")

    source_cutoff = datetime.now(UTC)
    history_paths = download_nflverse(args.history_seasons, args.raw_dir / "history")
    stats = read_table(history_paths["player_stats"])
    weekly_rosters = read_table(history_paths["rosters_weekly"])
    players = read_table(history_paths["players"])
    historical, diagnostics = build_preseason_season_dataset(
        stats,
        weekly_rosters,
        players=players,
        seasons=args.history_seasons,
        snapshot_week=1,
    )

    try:
        import nflreadpy as nfl
    except ImportError as exc:
        raise RuntimeError("nflreadpy is required for current-roster materialization") from exc
    current_rosters = _to_pandas(nfl.load_rosters([int(args.season)]))
    current_features = build_current_preseason_features(
        historical,
        current_rosters,
        season=int(args.season),
        players=players,
    )

    config = load_config(args.config)
    model, predictions = fit_preseason_candidate(
        historical,
        current_features,
        model_config=config.model,
    )
    product = build_preseason_product_frame(
        predictions,
        source_cutoff_utc=source_cutoff,
    )

    root = args.bundle_root
    root.mkdir(parents=True, exist_ok=True)
    model_path = model.save(root / "preseason_model.joblib")
    values_path = write_table(product, root / "product_player_values.csv")
    roster_path = write_table(current_features, root / "current_preseason_features.parquet")
    evidence = {
        "schema_version": 1,
        "authority": "challenger",
        "activation_eligible": False,
        "automatic_promotion": False,
        "season": int(args.season),
        "source_cutoff_utc": source_cutoff.isoformat(),
        "benchmark": {
            "git_sha": args.benchmark_git_sha,
            "artifact_digest": args.benchmark_artifact_digest,
            "reviewed_approved": True,
        },
        "historical_dataset_diagnostics": diagnostics.as_dict(),
        "current_rows": int(len(current_features)),
        "product_rows": int(len(product)),
        "decision_quantile_policy": "pending_uncertainty_qualification",
        "minor_scoring_components": "pending_separate_qualification",
    }
    evidence_path = root / "qualification_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = register_candidate_bundle(
        root,
        args.registry_root,
        model_path=model_path,
        predictions_path=values_path,
        roster_path=roster_path,
        evidence_path=evidence_path,
        source_cutoff_utc=source_cutoff,
        code_sha=os.getenv("GITHUB_SHA"),
        metadata={
            "benchmark_git_sha": args.benchmark_git_sha,
            "benchmark_artifact_digest": args.benchmark_artifact_digest,
            "uncertainty_qualified": False,
            "minor_scoring_components_qualified": False,
        },
    )
    print(
        json.dumps(
            {
                "bundle_id": manifest.bundle_id,
                "authority": manifest.authority,
                "activation_eligible": manifest.activation_eligible,
                "rows": len(product),
                "source_cutoff_utc": source_cutoff.isoformat(),
                "automatic_promotion": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
