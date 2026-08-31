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
    """Validate the current draft-release shape without importing the application package."""

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

    projection_path = root / os.getenv(
        "PSE_PROJECTIONS_PATH", "artifacts/predictions/product_player_values.csv"
    )
    projection_ok, projection_detail = _projection_contract_check(projection_path)
    hub_path = root / "data/product/nfl_hub/current.json"
    special_teams_path = root / "data/product/special_teams_market/current.json"
    league_count = _league_snapshot_count(root)
    checks.extend(
        [
            Check(
                "production_projection_artifact",
                projection_ok,
                f"{projection_path}: {projection_detail}",
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
            "draft data plane has been materialized."
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
            "A projection filename alone is insufficient: the strict data gate requires the current multicontract schema and decision-authority policies.",
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
                "the real multicontract projection, NFL Hub, K/DST, and league artifacts satisfy "
                "their release contracts."
            )

    if build_status != "READY":
        raise SystemExit(2)
    if args.strict_data and data_status != "READY":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
