from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine import __version__
from player_state_engine.data.io import read_table
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.learning.artifact_registry import resolve_champion_bundle
from player_state_engine.product.release_readiness import assess_sept1_release_readiness


def _projection_authority(
    *,
    registry_root: Path | None,
    bundle_root: Path | None,
    champion_target: str | None,
) -> tuple[str, bool, str | None, str | None]:
    supplied = [registry_root is not None, bundle_root is not None, bool(champion_target)]
    if not any(supplied):
        return (
            "unverified_path",
            False,
            None,
            "No immutable champion bundle was supplied.",
        )
    if not all(supplied):
        return (
            "unverified_path",
            False,
            None,
            "--registry-root, --bundle-root, and --champion-target must be supplied together.",
        )
    assert registry_root is not None
    assert bundle_root is not None
    assert champion_target is not None
    try:
        manifest = resolve_champion_bundle(registry_root, bundle_root, champion_target)
    except Exception as exc:  # noqa: BLE001 - operator report must preserve fail-closed evidence
        return "unverified_path", False, None, f"Champion resolution failed: {exc}"
    return manifest.authority, True, manifest.source_cutoff_utc, None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Produce one fail-closed Sept. 1 release verdict across immutable projection "
            "authority, current NFL Hub state, exact fantasy league contracts, and verified "
            "external-only K/DST support."
        )
    )
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument(
        "--league",
        action="append",
        type=Path,
        required=True,
        help="Repeat for every distinct fantasy league contract that must be supported.",
    )
    parser.add_argument("--nfl-hub", type=Path, required=True)
    parser.add_argument(
        "--special-teams-market",
        type=Path,
        help=(
            "Optional external_market_only K/DST snapshot. Required for PROVISIONAL release "
            "when a league's only unresolved required positions are K/DST."
        ),
    )
    parser.add_argument("--registry-root", type=Path)
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--champion-target")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--strict-ready",
        action="store_true",
        help="Exit 2 unless the exact release verdict is READY.",
    )
    parser.add_argument(
        "--allow-provisional",
        action="store_true",
        help="Exit 2 only for BLOCKED; still prints every provisional exception.",
    )
    parser.add_argument("--max-projection-age-hours", type=float, default=48.0)
    parser.add_argument("--max-hub-age-hours", type=float, default=12.0)
    parser.add_argument("--max-special-teams-market-age-hours", type=float, default=48.0)
    args = parser.parse_args()

    projections = read_table(args.projections)
    leagues = {path.stem: LeagueConfig.from_yaml(path) for path in args.league}
    hub = json.loads(args.nfl_hub.read_text(encoding="utf-8"))
    special_teams = (
        json.loads(args.special_teams_market.read_text(encoding="utf-8"))
        if args.special_teams_market is not None
        else None
    )
    authority, integrity, source_cutoff, resolution_error = _projection_authority(
        registry_root=args.registry_root,
        bundle_root=args.bundle_root,
        champion_target=args.champion_target,
    )
    report = assess_sept1_release_readiness(
        projections,
        leagues,
        package_version=__version__,
        projection_authority=authority,
        projection_integrity_verified=integrity,
        projection_source_cutoff_utc=source_cutoff,
        nfl_hub_snapshot=hub,
        special_teams_market_snapshot=special_teams,
        max_projection_age_hours=args.max_projection_age_hours,
        max_hub_age_hours=args.max_hub_age_hours,
        max_special_teams_market_age_hours=args.max_special_teams_market_age_hours,
    )
    payload = report.as_dict()
    payload["projection_resolution_error"] = resolution_error
    payload["projection_path"] = str(args.projections)
    payload["nfl_hub_path"] = str(args.nfl_hub)
    payload["special_teams_market_path"] = (
        str(args.special_teams_market) if args.special_teams_market is not None else None
    )
    payload["league_paths"] = [str(path) for path in args.league]
    rendered = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    print(rendered, end="")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(rendered, encoding="utf-8")

    if args.strict_ready and report.status != "READY":
        raise SystemExit(2)
    if args.allow_provisional and report.status == "BLOCKED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
