from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

EXPECTED_RELEASE_PREFIX = "0.17."
MIN_PYTHON = (3, 11)
MIN_NODE_MAJOR = 22


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
    hub_path = root / "data/product/nfl_hub/current.json"
    special_teams_path = root / "data/product/special_teams_market/current.json"
    league_count = _league_snapshot_count(root)
    checks.extend(
        [
            Check(
                "production_projection_artifact",
                projection_path.is_file(),
                str(projection_path),
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
        help="Exit nonzero if live draft artifacts are missing.",
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
                "the real projection, NFL Hub, K/DST, and league artifacts exist."
            )

    if build_status != "READY":
        raise SystemExit(2)
    if args.strict_data and data_status != "READY":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
