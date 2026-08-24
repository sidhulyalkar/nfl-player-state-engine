from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table, write_table
from player_state_engine.evaluation.evidence_factory import (
    EvidenceBundle,
    build_evidence_bundle,
    canonicalize_predictions,
)
from player_state_engine.fantasy.league import LeagueConfig

DEFAULT_TARGETS = (
    "fantasy_points_ppr",
    "targets",
    "carries",
    "receptions",
    "receiving_yards",
    "rushing_yards",
    "passing_yards",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_record(path: Path, *, role: str) -> dict[str, object]:
    return {
        "role": role,
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


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


def _graph_scoring_status(manifest: dict[str, object]) -> dict[str, object]:
    contract = manifest.get("league_contract")
    if not isinstance(contract, dict):
        return {"comparable": False, "reason": "graph_league_contract_missing"}
    weights = contract.get("scoring_weights")
    if not isinstance(weights, dict):
        return {"comparable": False, "reason": "graph_scoring_weights_missing"}
    try:
        graph_weights = {str(key): float(value) for key, value in weights.items()}
        graph_premium = float(contract.get("tight_end_premium", 0.0) or 0.0)
    except (TypeError, ValueError):
        return {"comparable": False, "reason": "graph_scoring_contract_invalid"}
    production = LeagueConfig(scoring="ppr")
    comparable = graph_weights == production.scoring_weights and graph_premium == float(
        production.tight_end_premium
    )
    return {
        "comparable": comparable,
        "reason": "exact_ppr_scoring_match" if comparable else "graph_scoring_contract_mismatch",
        "tight_end_premium_match": graph_premium == float(production.tight_end_premium),
        "base_weights_match": graph_weights == production.scoring_weights,
    }


def _load_benchmark_target(
    benchmark_root: Path,
    target: str,
) -> tuple[list[pd.DataFrame], list[dict[str, object]]]:
    path = benchmark_root / target / f"{target}_predictions.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Benchmark prediction artifact unavailable: {path}")
    frames = [canonicalize_predictions(read_table(path), target=target, source="benchmark")]
    inputs = [_input_record(path, role=f"benchmark:{target}")]

    if target == "carries":
        corrected_path = benchmark_root / target / "carries_position_specific_predictions.csv"
        if corrected_path.is_file():
            frames.append(
                canonicalize_predictions(
                    read_table(corrected_path),
                    target=target,
                    method="position_specific_quantile",
                    source="benchmark_position_specific",
                )
            )
            inputs.append(_input_record(corrected_path, role="benchmark:carries_position_specific"))
    return frames, inputs


def _load_graph(
    graph_root: Path,
) -> tuple[pd.DataFrame | None, list[dict[str, object]], dict[str, object]]:
    summary_path = graph_root / "player_state_graph_summaries.parquet"
    manifest_path = graph_root / "run_manifest.json"
    if not summary_path.is_file() or not manifest_path.is_file():
        return None, [], {
            "included": False,
            "reason": "graph_summary_or_manifest_unavailable",
            "summary_available": summary_path.is_file(),
            "manifest_available": manifest_path.is_file(),
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, [_input_record(summary_path, role="player_state_graph")], {
            "included": False,
            "reason": "graph_manifest_invalid_json",
        }
    if not isinstance(manifest, dict):
        return None, [], {"included": False, "reason": "graph_manifest_not_object"}
    scoring = _graph_scoring_status(manifest)
    records = [
        _input_record(summary_path, role="player_state_graph"),
        _input_record(manifest_path, role="player_state_graph_manifest"),
    ]
    if not scoring["comparable"]:
        return None, records, {"included": False, **scoring}
    frame = canonicalize_predictions(
        read_table(summary_path),
        target="fantasy_points_ppr",
        method="player_state_graph",
        source="player_state_graph",
    )
    return frame, records, {"included": True, **scoring, "rows": len(frame)}


def _persist_bundle(bundle: EvidenceBundle, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "canonical_predictions": write_table(
            bundle.predictions, output_dir / "canonical_predictions.parquet"
        ),
        "method_summary": write_table(bundle.method_summary, output_dir / "method_summary.csv"),
        "slice_metrics": write_table(bundle.slice_metrics, output_dir / "slice_metrics.csv"),
        "paired_comparisons": write_table(
            bundle.paired_comparisons, output_dir / "paired_comparisons.csv"
        ),
        "experiment_ledger": write_table(
            bundle.experiment_ledger, output_dir / "experiment_ledger.csv"
        ),
    }
    return {name: str(path) for name, path in paths.items()}


def _write_report(bundle: EvidenceBundle, output_dir: Path, graph_status: dict[str, object]) -> Path:
    path = output_dir / "report.md"
    summary = bundle.method_summary.sort_values(["target", "mean_pinball"], kind="mergesort")
    comparisons = bundle.paired_comparisons.sort_values(
        ["target", "challenger"], kind="mergesort"
    )
    lines = [
        "# Evidence Factory frozen benchmark",
        "",
        "All comparisons are paired on identical frozen player-weeks. Positive paired pinball effect means the challenger beat the production champion on mean quantile loss.",
        "",
        "## Authority",
        "",
        "This artifact is evidence, not automatic model promotion. The direct quantile model remains production-authoritative unless the fail-closed promotion policy clears all required tiers and blockers.",
        "",
        "## Method summary",
        "",
        summary.to_markdown(index=False) if not summary.empty else "No method metrics available.",
        "",
        "## Paired comparisons",
        "",
        comparisons.to_markdown(index=False) if not comparisons.empty else "No paired comparisons available.",
        "",
        "## Player State Graph ingestion",
        "",
        f"```json\n{json.dumps(graph_status, indent=2, default=str)}\n```",
        "",
        "## Interpretation",
        "",
        "A lower loss alone is insufficient. Read interval coverage, sharpness, season/position/week consistency, overlap, negative controls, downstream decision evidence, and evidence tier together.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> None:
    benchmark_root = Path(args.benchmark_root)
    graph_root = Path(args.graph_root)
    output_dir = Path(args.output_dir)
    frames: list[pd.DataFrame] = []
    input_records: list[dict[str, object]] = []
    targets = tuple(args.targets or DEFAULT_TARGETS)

    for target in targets:
        target_frames, records = _load_benchmark_target(benchmark_root, target)
        frames.extend(target_frames)
        input_records.extend(records)

    graph_frame, graph_records, graph_status = _load_graph(graph_root)
    input_records.extend(graph_records)
    if graph_frame is not None and "fantasy_points_ppr" in targets:
        frames.append(graph_frame)

    bundle = build_evidence_bundle(
        frames,
        champion_method=args.champion_method,
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
        calibration_tolerance=args.calibration_tolerance,
    )
    outputs = _persist_bundle(bundle, output_dir)
    report = _write_report(bundle, output_dir, graph_status)
    outputs["report"] = str(report)

    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "authority": "research_evidence_only",
        "git_sha": _git_sha(),
        "champion_method": args.champion_method,
        "targets": list(targets),
        "bootstrap_samples": int(args.bootstrap_samples),
        "seed": int(args.seed),
        "calibration_tolerance": float(args.calibration_tolerance),
        "inputs": input_records,
        "graph": graph_status,
        "outputs": outputs,
        "promotion": {
            "automatic": False,
            "note": "Evidence Factory records are inputs to the fail-closed promotion policy, not promotion events.",
        },
    }
    manifest_path = output_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Evidence Factory complete: {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build one canonical frozen evidence ledger across production and research models."
    )
    parser.add_argument("--benchmark-root", default="artifacts/reports/benchmark_real")
    parser.add_argument("--graph-root", default="artifacts/player_state_graph")
    parser.add_argument("--output-dir", default="artifacts/evidence_factory")
    parser.add_argument("--targets", nargs="+")
    parser.add_argument("--champion-method", default="quantile_engine")
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--calibration-tolerance", type=float, default=0.05)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
