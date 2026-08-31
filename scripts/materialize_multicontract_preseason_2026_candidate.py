from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.config import load_config
from player_state_engine.data.io import read_table, write_table
from player_state_engine.data.nflverse import download_nflverse
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.preseason import (
    build_current_preseason_features,
    build_preseason_season_dataset,
)
from player_state_engine.learning.artifact_registry import (
    build_artifact_bundle,
    save_artifact_bundle_manifest,
    sha256_file,
    verify_artifact_bundle,
)
from player_state_engine.models.conformal import TargetPositionConformalCalibrator
from player_state_engine.product.nfl_hub import _to_pandas
from player_state_engine.product.preseason_multicontract_candidate import (
    BUNDLE_TARGET,
    MODEL_ID,
    PPR_POLICY,
    build_contract_product_frame,
    combine_contract_product_frames,
    fit_direct_contract_candidate,
    market_context_from_nfl_hub,
    validate_release_evidence,
)

DEFAULT_LEAGUES = (
    Path("configs/fantasy/8_team_ppr_2qb_expanded.yaml"),
    Path("configs/fantasy/12_team_half_ppr_median.yaml"),
)


def _slug(path: Path) -> str:
    return path.stem.replace(" ", "_")


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _config_digest(base_config: Path, league_paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in (base_config, *sorted(league_paths, key=lambda item: item.as_posix())):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the evidence-bound 2026 PPR + half-PPR direct-score challenger. "
            "This command cannot create production authority or move a champion pointer."
        )
    )
    parser.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument("--league", type=Path, action="append", default=[])
    parser.add_argument("--history-seasons", nargs="+", type=int, default=list(range(2015, 2026)))
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/preseason_2026_multicontract"))
    parser.add_argument("--direct-evidence-root", type=Path, required=True)
    parser.add_argument("--uncertainty-evidence-root", type=Path, required=True)
    parser.add_argument("--nfl-hub-snapshot", type=Path, required=True)
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--registry-root", type=Path, default=Path("artifacts/registry"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    league_paths = tuple(args.league or DEFAULT_LEAGUES)
    leagues = {_slug(path): LeagueConfig.from_yaml(path) for path in league_paths}
    if set(leagues) != {"8_team_ppr_2qb_expanded", "12_team_half_ppr_median"}:
        raise ValueError(
            "The frozen v0.17 materializer requires the reviewed PPR and half-PPR league configs"
        )

    direct_manifest_path = args.direct_evidence_root / "qualification.json"
    uncertainty_manifest_path = args.uncertainty_evidence_root / "qualification.json"
    direct_sha = sha256_file(direct_manifest_path)
    uncertainty_sha = sha256_file(uncertainty_manifest_path)
    evidence = validate_release_evidence(
        direct_manifest_path,
        uncertainty_manifest_path,
        leagues,
        direct_manifest_sha256=direct_sha,
        uncertainty_manifest_sha256=uncertainty_sha,
    )

    hub = _json(args.nfl_hub_snapshot)
    market_context = market_context_from_nfl_hub(hub)
    market_rows = int(market_context["market_adp"].notna().sum()) if not market_context.empty else 0
    if market_rows < 250:
        raise RuntimeError(
            "Current NFL Hub market context is too sparse for release materialization: "
            f"market_adp_rows={market_rows}"
        )

    history_paths = download_nflverse(args.history_seasons, args.raw_dir / "history")
    stats = read_table(history_paths["player_stats"])
    weekly_rosters = read_table(history_paths["rosters_weekly"])
    players = read_table(history_paths["players"])
    historical, historical_diagnostics = build_preseason_season_dataset(
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
    source_cutoff = datetime.now(UTC)
    current_features = build_current_preseason_features(
        historical,
        current_rosters,
        season=int(args.season),
        players=players,
    )
    if len(current_features) < 250:
        raise RuntimeError(f"Current preseason skill-player universe is unexpectedly small: {len(current_features)}")

    engine = load_config(args.config)
    root = args.bundle_root
    root.mkdir(parents=True, exist_ok=True)
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "calibrators").mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(parents=True, exist_ok=True)

    contract_frames: dict[str, object] = {}
    target_diagnostics: dict[str, object] = {}
    model_paths: dict[str, Path] = {}
    calibrator_paths: dict[str, Path] = {}
    for slug, league in leagues.items():
        model, predictions, diagnostics = fit_direct_contract_candidate(
            historical,
            stats,
            current_features,
            league,
            model_config=engine.model,
        )
        target_diagnostics[slug] = diagnostics.as_dict()
        model_path = model.save(root / "models" / f"{slug}.joblib")
        model_paths[slug] = model_path

        calibrator = None
        contract_evidence = evidence[slug]
        if contract_evidence.decision_quantile_policy == PPR_POLICY:
            source_calibrator = args.uncertainty_evidence_root / slug / "calibrator.joblib"
            if not source_calibrator.is_file():
                raise FileNotFoundError(
                    f"Qualified PPR calibrator is missing from uncertainty evidence: {source_calibrator}"
                )
            calibrator = TargetPositionConformalCalibrator.load(source_calibrator)
            if calibrator.fitted_through_season != max(args.history_seasons):
                raise RuntimeError(
                    "PPR calibrator history cutoff does not match completed training history: "
                    f"{calibrator.fitted_through_season} != {max(args.history_seasons)}"
                )
            copied = root / "calibrators" / f"{slug}.joblib"
            shutil.copy2(source_calibrator, copied)
            calibrator_paths[slug] = copied

        frame = build_contract_product_frame(
            predictions,
            current_features,
            league,
            contract_evidence,
            source_cutoff_utc=source_cutoff,
            market_context=market_context,
            calibrator=calibrator,
        )
        contract_frames[slug] = frame

    product = combine_contract_product_frames(contract_frames)  # type: ignore[arg-type]
    values_path = write_table(product, root / "product_player_values.csv")
    features_path = write_table(current_features, root / "current_preseason_features.parquet")

    copied_direct = root / "evidence" / "direct_league_score_qualification.json"
    copied_uncertainty = root / "evidence" / "uncertainty_qualification.json"
    shutil.copy2(direct_manifest_path, copied_direct)
    shutil.copy2(uncertainty_manifest_path, copied_uncertainty)

    contract_metadata = {
        slug: {
            **item.as_dict(),
            "scoring_contract_payload": leagues[slug].scoring_contract_payload(),
            "model_path": model_paths[slug].relative_to(root).as_posix(),
            "calibrator_path": (
                calibrator_paths[slug].relative_to(root).as_posix()
                if slug in calibrator_paths
                else None
            ),
            "rows": int(len(contract_frames[slug])),  # type: ignore[arg-type]
            "market_adp_coverage": float(
                contract_frames[slug]["market_adp"].notna().mean()  # type: ignore[index]
            ),
        }
        for slug, item in evidence.items()
    }
    contract_metadata_path = root / "contract_metadata.json"
    contract_metadata_path.write_text(
        json.dumps(contract_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    qualification = {
        "schema_version": 2,
        "authority": "challenger",
        "activation_eligible": False,
        "automatic_promotion": False,
        "season": int(args.season),
        "model_id": MODEL_ID,
        "target": BUNDLE_TARGET,
        "source_cutoff_utc": source_cutoff.isoformat(),
        "history_seasons": [int(value) for value in args.history_seasons],
        "historical_dataset_diagnostics": historical_diagnostics.as_dict(),
        "target_diagnostics": target_diagnostics,
        "current_feature_rows": int(len(current_features)),
        "product_rows": int(len(product)),
        "unique_current_players": int(product["player_id"].nunique()),
        "scoring_contracts": contract_metadata,
        "research_evidence": {
            "direct_manifest_sha256": direct_sha,
            "uncertainty_manifest_sha256": uncertainty_sha,
            "direct_manifest_authority": _json(direct_manifest_path).get("authority"),
            "uncertainty_manifest_authority": _json(uncertainty_manifest_path).get("authority"),
        },
        "nfl_hub": {
            "authority": hub.get("authority"),
            "generated_at_utc": hub.get("generated_at_utc"),
            "market_adp_rows": market_rows,
            "market_identity": hub.get("market_identity"),
        },
        "release_boundary": (
            "This bundle is a challenger only. Run the multicontract release rehearsal against "
            "fresh NFL Hub and external-only K/DST evidence, then create a separate manually "
            "approved production manifest over the exact same bytes before champion promotion."
        ),
    }
    qualification_path = root / "qualification_evidence.json"
    qualification_path.write_text(
        json.dumps(qualification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    files: dict[str, Path] = {
        "player_values": values_path,
        "current_preseason_features": features_path,
        "qualification_evidence": qualification_path,
        "contract_metadata": contract_metadata_path,
        "direct_score_evidence": copied_direct,
        "uncertainty_evidence": copied_uncertainty,
    }
    files.update({f"model_{slug}": path for slug, path in model_paths.items()})
    files.update({f"calibrator_{slug}": path for slug, path in calibrator_paths.items()})

    manifest = build_artifact_bundle(
        root,
        files,
        artifact_type="preseason_multicontract_player_values_candidate",
        authority="challenger",
        activation_eligible=False,
        model_id=MODEL_ID,
        target=BUNDLE_TARGET,
        code_sha=os.getenv("GITHUB_SHA"),
        config_sha256=_config_digest(args.config, league_paths),
        source_cutoff_utc=source_cutoff.isoformat(),
        metadata={
            "season": int(args.season),
            "automatic_promotion": False,
            "scoring_contract_ids": {
                slug: league.scoring_contract_id for slug, league in leagues.items()
            },
            "decision_quantile_policies": {
                slug: evidence[slug].decision_quantile_policy for slug in leagues
            },
            "direct_evidence_sha256": direct_sha,
            "uncertainty_evidence_sha256": uncertainty_sha,
        },
    )
    manifest_path = save_artifact_bundle_manifest(manifest, args.registry_root)
    health = verify_artifact_bundle(manifest, root)
    if not health["integrity_verified"]:
        raise RuntimeError(f"New candidate bundle failed byte verification: {health['failures']}")

    print(
        json.dumps(
            {
                "bundle_id": manifest.bundle_id,
                "manifest_path": str(manifest_path),
                "authority": manifest.authority,
                "activation_eligible": manifest.activation_eligible,
                "source_cutoff_utc": source_cutoff.isoformat(),
                "product_rows": int(len(product)),
                "unique_players": int(product["player_id"].nunique()),
                "contracts": contract_metadata,
                "integrity_verified": True,
                "automatic_promotion": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
