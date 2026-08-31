from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

EXPECTED_RELEASE_PREFIX = "0.17."
MIN_PYTHON = (3, 11)
MIN_NODE_MAJOR = 22
_REQUIRED_PROJECTION_COLUMNS = {
    "scoring_contract_id",
    "player_id",
    "league_season_points_q50",
    "league_scoring_exact",
    "decision_quantile_policy",
}
_REQUIRED_DECISION_POLICIES = {"qualified_distribution", "q50_only"}
_DEFAULT_PROJECTION_PATH = "artifacts/predictions/product_player_values.csv"
_DEFAULT_REGISTRY_ROOT = "artifacts/registry"
_DEFAULT_CHAMPION_TARGET = "preseason_multicontract_player_values_2026"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    layer: str


def _command_version(command: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    text = (result.stdout or result.stderr).strip()
    return result.returncode == 0, text


def _node_major(version_text: str) -> int | None:
    match = re.search(r"v?(\d+)", version_text)
    return int(match.group(1)) if match else None


def _league_snapshot_count(root: Path) -> int:
    count = 0
    for directory in (root / "data/product/leagues", root / "data/product/live_leagues"):
        if directory.exists():
            count += sum(1 for path in directory.glob("*.json") if path.is_file())
    return count


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def _projection_contract_check(path: Path) -> tuple[bool, str]:
    """Validate the current multicontract player-values shape."""

    if not path.is_file():
        return False, f"unavailable: {path}"
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or ())
            missing = sorted(_REQUIRED_PROJECTION_COLUMNS - columns)
            if missing:
                return False, f"legacy/incomplete projection schema; missing={missing}"

            rows = 0
            contracts: dict[str, set[str]] = defaultdict(set)
            contract_policies: dict[str, set[str]] = defaultdict(set)
            duplicate_pairs: list[str] = []
            invalid_rows = 0
            for row in reader:
                rows += 1
                contract_id = str(row.get("scoring_contract_id") or "").strip()
                player_id = str(row.get("player_id") or "").strip()
                policy = str(row.get("decision_quantile_policy") or "").strip().lower()
                q50 = str(row.get("league_season_points_q50") or "").strip()
                if not contract_id or not player_id or not policy or not q50:
                    invalid_rows += 1
                    continue
                if not _truthy(row.get("league_scoring_exact")):
                    invalid_rows += 1
                    continue
                if player_id in contracts[contract_id]:
                    duplicate_pairs.append(f"{contract_id}:{player_id}")
                contracts[contract_id].add(player_id)
                contract_policies[contract_id].add(policy)
    except (OSError, UnicodeError, csv.Error) as exc:
        return False, f"unreadable projection artifact: {exc}"

    if rows == 0:
        return False, "projection artifact is empty"
    if invalid_rows:
        return False, f"{invalid_rows} projection row(s) violate required contract fields"
    if duplicate_pairs:
        return False, f"duplicate contract/player rows: {duplicate_pairs[:5]}"
    if len(contracts) < 2:
        return False, f"expected multicontract release artifact; found {len(contracts)} contract(s)"
    nonuniform = {
        contract_id: sorted(policies)
        for contract_id, policies in contract_policies.items()
        if len(policies) != 1
    }
    if nonuniform:
        return False, f"decision policy is not uniform within contracts: {nonuniform}"
    policies = {next(iter(values)) for values in contract_policies.values() if values}
    missing_policies = sorted(_REQUIRED_DECISION_POLICIES - policies)
    if missing_policies:
        return False, f"current release policies missing from artifact: {missing_policies}"
    smallest_contract = min(len(players) for players in contracts.values())
    if smallest_contract < 250:
        return False, f"contract player coverage too small: min_rows={smallest_contract}"
    return (
        True,
        f"{rows} rows; {len(contracts)} contracts; min_contract_rows={smallest_contract}; "
        f"policies={sorted(policies)}",
    )


def _rooted(root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else root / path


def _production_projection_check(root: Path) -> tuple[bool, str]:
    """Require the same verified champion authority used by the live Product API.

    A schema-valid path is useful for development, but it is deliberately insufficient for the
    actual-draft data gate. Production readiness requires an explicitly promoted champion whose
    immutable bytes are re-verified by ``ProjectionArtifactSource`` before the schema check runs.
    """

    mode = str(os.getenv("PSE_PROJECTION_SOURCE_MODE", "path")).strip().lower()
    if mode == "path":
        path = _rooted(root, os.getenv("PSE_PROJECTIONS_PATH", _DEFAULT_PROJECTION_PATH))
        schema_ok, detail = _projection_contract_check(path)
        if not schema_ok:
            return False, f"source_mode=path_unverified; {path}: {detail}"
        return (
            False,
            "source_mode=path_unverified; multicontract schema is valid but actual-draft "
            "readiness requires PSE_PROJECTION_SOURCE_MODE=champion",
        )
    if mode != "champion":
        return False, f"unsupported PSE_PROJECTION_SOURCE_MODE={mode!r}"

    raw_bundle_root = str(os.getenv("PSE_PRODUCTION_BUNDLE_ROOT", "")).strip()
    if not raw_bundle_root:
        return False, "champion mode requires PSE_PRODUCTION_BUNDLE_ROOT"

    registry_root = _rooted(
        root,
        os.getenv("PSE_ARTIFACT_REGISTRY_ROOT", _DEFAULT_REGISTRY_ROOT),
    )
    bundle_root = _rooted(root, raw_bundle_root)
    target = str(
        os.getenv("PSE_PROJECTION_CHAMPION_TARGET", _DEFAULT_CHAMPION_TARGET)
    ).strip()
    if not target:
        return False, "champion mode requires a non-empty PSE_PROJECTION_CHAMPION_TARGET"

    try:
        from player_state_engine.product.projection_artifact_source import ProjectionArtifactSource

        source = ProjectionArtifactSource(
            mode="champion",
            registry_root=registry_root,
            bundle_root=bundle_root,
            champion_target=target,
        )
        snapshot = source.load()
    except (ImportError, OSError, KeyError, ValueError, PermissionError, RuntimeError) as exc:
        return False, f"verified champion unavailable: {exc}"

    if snapshot.authority != "production_approved" or not snapshot.integrity_verified:
        return False, (
            f"champion authority invalid: authority={snapshot.authority!r}; "
            f"integrity_verified={snapshot.integrity_verified}"
        )
    schema_ok, detail = _projection_contract_check(snapshot.path)
    if not schema_ok:
        return False, f"verified champion schema invalid: {detail}"
    return (
        True,
        f"verified champion bundle={snapshot.bundle_id}; target={snapshot.target}; {detail}",
    )


def run_preflight(root: Path) -> list[Check]:
    checks: list[Check] = []

    python_ok = sys.version_info >= MIN_PYTHON
    checks.append(
        Check(
            "python",
            python_ok,
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} "
            f"(required >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})",
            "build",
        )
    )

    node_ok, node_version = _command_version("node")
    node_major = _node_major(node_version) if node_ok else None
    checks.append(
        Check(
            "node",
            bool(node_ok and node_major is not None and node_major >= MIN_NODE_MAJOR),
            f"{node_version or 'not found'} (required >= {MIN_NODE_MAJOR})",
            "build",
        )
    )
    npm_ok, npm_version = _command_version("npm")
    checks.append(Check("npm", npm_ok, npm_version or "not found", "build"))

    for relative in (
        "pyproject.toml",
        "apps/gemini-fantasy-console/package.json",
        "apps/gemini-fantasy-console/package-lock.json",
        "apps/gemini-fantasy-console/.env.example",
        "configs/fantasy/8_team_ppr_2qb_expanded.yaml",
        "configs/fantasy/12_team_half_ppr_median.yaml",
        "configs/fantasy/12_team_half_ppr_median_2qb.yaml",
    ):
        path = root / relative
        checks.append(Check(relative, path.is_file(), str(path), "build"))

    try:
        import tomllib

        metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        package_version = str(metadata["project"]["version"])
        version_ok = package_version.startswith(EXPECTED_RELEASE_PREFIX)
    except (OSError, KeyError, ValueError) as exc:
        package_version = f"unreadable: {exc}"
        version_ok = False
    checks.append(
        Check(
            "release_version",
            version_ok,
            f"{package_version} (required {EXPECTED_RELEASE_PREFIX}x)",
            "build",
        )
    )

    projection_ok, projection_detail = _production_projection_check(root)
    hub_path = root / "data/product/nfl_hub/current.json"
    special_teams_path = root / "data/product/special_teams_market/current.json"
    league_count = _league_snapshot_count(root)
    checks.extend(
        [
            Check(
                "production_projection_champion",
                projection_ok,
                projection_detail,
                "data",
            ),
            Check("nfl_hub_snapshot", hub_path.is_file(), str(hub_path), "data"),
            Check(
                "special_teams_market_snapshot",
                special_teams_path.is_file(),
                str(special_teams_path),
                "data",
            ),
            Check(
                "league_snapshots",
                league_count > 0,
                f"{league_count} JSON snapshot(s) across data/product/leagues and live_leagues",
                "data",
            ),
        ]
    )
    return checks


def _status(checks: list[Check], layer: str) -> str:
    selected = [check for check in checks if check.layer == layer]
    return "READY" if selected and all(check.ok for check in selected) else "BLOCKED"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether a fresh checkout can build the draft workspace and whether the real "
            "draft data plane has been materialized and promoted."
        )
    )
    parser.add_argument(
        "--strict-data",
        action="store_true",
        help="Exit nonzero if live draft artifacts are missing or violate release contracts.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON for coding agents.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    checks = run_preflight(root)
    build_status = _status(checks, "build")
    data_status = _status(checks, "data")
    payload = {
        "build_status": build_status,
        "draft_data_status": data_status,
        "strict_data": bool(args.strict_data),
        "checks": [asdict(check) for check in checks],
        "notes": [
            "The React/Express workspace can build without GEMINI_API_KEY; copilot falls back to deterministic Product API tools.",
            "Actual-draft projection readiness requires the byte-verified production champion; path mode is development authority only.",
            "The champion must also contain the current multicontract schema and qualified decision-authority policies.",
            "Missing draft-data artifacts must remain unavailable. Do not fabricate frontend placeholder projections to satisfy strict preflight.",
        ],
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for check in checks:
            marker = "OK" if check.ok else "MISSING"
            print(f"[{marker:7}] {check.layer:5} {check.name}: {check.detail}")
        print(f"\nBuild preflight: {build_status}")
        print(f"Draft data plane: {data_status}")
        if data_status != "READY":
            print(
                "The UI may still build, but draft recommendations are not release-ready until "
                "the verified production champion, NFL Hub, K/DST, and league artifacts satisfy "
                "their release contracts."
            )

    if build_status != "READY":
        raise SystemExit(2)
    if args.strict_data and data_status != "READY":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
