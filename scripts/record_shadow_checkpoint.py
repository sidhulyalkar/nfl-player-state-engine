from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.product.shadow_season import (
    SHADOW_CHECKPOINTS,
    ShadowSeasonStore,
    attach_research_challenger,
    build_shadow_snapshot,
    normalize_production_forecasts,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _decision_records(
    path: Path | None,
    *,
    cutoff: pd.Timestamp,
    league_key: str | None,
) -> list[dict[str, object]]:
    if path is None:
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"Decision audit line is not an object: {path}")
        if payload.get("recorded_at") is None:
            raise ValueError(f"Decision audit line is missing recorded_at: {path}")
        recorded = pd.Timestamp(payload["recorded_at"])
        if recorded.tzinfo is None:
            recorded = recorded.tz_localize("UTC")
        else:
            recorded = recorded.tz_convert("UTC")
        if recorded > cutoff:
            continue
        if league_key is not None and str(payload.get("league_key")) != league_key:
            continue
        rows.append(payload)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze one immutable 2026 live shadow-season forecast checkpoint."
    )
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--checkpoint", choices=SHADOW_CHECKPOINTS, required=True)
    parser.add_argument(
        "--prediction-cutoff",
        required=True,
        help="ISO-8601 UTC-aware cutoff",
    )
    parser.add_argument(
        "--projection-available-at",
        required=True,
        help="When the production projection artifact first became available",
    )
    parser.add_argument("--league-key", default=None)
    parser.add_argument("--production-method", default="direct_player_quantile_model")
    parser.add_argument("--challenger", type=Path, default=None)
    parser.add_argument("--challenger-available-at", default=None)
    parser.add_argument("--challenger-method", default="player_state_graph")
    parser.add_argument("--decision-jsonl", type=Path, default=None)
    parser.add_argument("--model-metadata", type=Path, default=None)
    parser.add_argument("--source-manifest", type=Path, default=None)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/shadow_season"),
    )
    args = parser.parse_args()

    cutoff = pd.Timestamp(args.prediction_cutoff)
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")

    production_raw = read_table(args.projections)
    production = normalize_production_forecasts(
        production_raw,
        production_method=args.production_method,
    )

    if args.challenger is not None:
        challenger = read_table(args.challenger)
        if "season" in challenger:
            challenger = challenger.loc[
                pd.to_numeric(challenger["season"], errors="coerce").eq(args.season)
            ].copy()
        if "week" in challenger:
            challenger = challenger.loc[
                pd.to_numeric(challenger["week"], errors="coerce").eq(args.week)
            ].copy()
        production = attach_research_challenger(
            production,
            challenger,
            challenger_method=args.challenger_method,
        )

    sources: list[dict[str, object]] = [
        {
            "name": "production_projections",
            "available_at": args.projection_available_at,
            "sha256": _sha256(args.projections),
            "path": str(args.projections),
        }
    ]
    if args.challenger is not None:
        if args.challenger_available_at is None:
            raise ValueError("--challenger-available-at is required with --challenger")
        sources.append(
            {
                "name": "player_state_graph_challenger",
                "available_at": args.challenger_available_at,
                "sha256": _sha256(args.challenger),
                "path": str(args.challenger),
            }
        )

    source_manifest = _json_object(args.source_manifest)
    extra_sources = source_manifest.get("sources", [])
    if extra_sources:
        if not isinstance(extra_sources, list) or not all(
            isinstance(item, dict) for item in extra_sources
        ):
            raise ValueError("source manifest 'sources' must be a list of objects")
        missing_timestamps = [
            str(item.get("name") or f"source[{index}]")
            for index, item in enumerate(extra_sources)
            if item.get("available_at") is None
        ]
        if missing_timestamps:
            raise ValueError(
                "Every auxiliary shadow source requires available_at; missing for "
                f"{missing_timestamps}"
            )
        sources.extend(extra_sources)

    snapshot = build_shadow_snapshot(
        production,
        season=args.season,
        week=args.week,
        checkpoint=args.checkpoint,
        prediction_cutoff=cutoff,
        captured_at=datetime.now(UTC),
        league_key=args.league_key,
        sources=sources,
        decision_records=_decision_records(
            args.decision_jsonl,
            cutoff=cutoff,
            league_key=args.league_key,
        ),
        model_metadata=_json_object(args.model_metadata),
    )
    store = ShadowSeasonStore(args.output_root)
    created = store.save_snapshot(snapshot)
    print(
        json.dumps(
            {
                "created": created,
                "snapshot_id": snapshot["snapshot_id"],
                "content_sha256": snapshot["content_sha256"],
                "path": str(store.snapshot_path(snapshot)),
                "forecast_count": snapshot["forecast_count"],
                "checkpoint": snapshot["checkpoint"],
                "prediction_cutoff": snapshot["prediction_cutoff"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
