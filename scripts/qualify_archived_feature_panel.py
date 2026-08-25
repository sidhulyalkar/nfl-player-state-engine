from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

_SCHEDULE_CONTEXT_COLUMNS = (
    "game_id",
    "season",
    "week",
    "gameday",
    "game_type",
    "away_team",
    "home_team",
    "spread_line",
    "total_line",
    "roof",
    "surface",
    "temp",
    "wind",
    "away_rest",
    "home_rest",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _records(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = payload.get("sources")
    if not isinstance(raw, list):
        raise ValueError("source manifest must contain a sources list")
    output: dict[str, dict[str, object]] = {}
    for row in raw:
        if not isinstance(row, dict) or not row.get("name"):
            raise ValueError("source manifest contains an invalid source record")
        output[str(row["name"])] = row
    return output


def _matches(path: Path, record: dict[str, object]) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == int(record["bytes"])
        and _sha256(path) == str(record["sha256"]).lower()
    )


def _github_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "nfl-player-state-engine/archived-feature-qualification",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _candidate_commits(until: str, limit: int = 40) -> list[str]:
    parsed = datetime.fromisoformat(until.replace("Z", "+00:00"))
    stamp = parsed.isoformat().replace("+00:00", "Z")
    query = urllib.parse.urlencode(
        {
            "path": "data/games.csv",
            "until": stamp,
            "per_page": min(max(limit, 1), 100),
        }
    )
    payload = _github_json(f"https://api.github.com/repos/nflverse/nfldata/commits?{query}")
    if not isinstance(payload, list):
        raise ValueError("Unexpected nfldata commit response")
    return [str(row["sha"]) for row in payload if isinstance(row, dict) and row.get("sha")]


def _recover_schedule(
    record: dict[str, object], *, until: str, output: Path, label: str
) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    if _matches(output, record):
        return {
            "label": label,
            "status": "already_exact",
            "path": output.as_posix(),
            "sha256": _sha256(output),
            "bytes": output.stat().st_size,
        }

    attempts: list[dict[str, object]] = []
    for commit in _candidate_commits(until):
        url = f"https://raw.githubusercontent.com/nflverse/nfldata/{commit}/data/games.csv"
        temporary = output.with_suffix(f".{commit[:8]}.partial")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "nfl-player-state-engine/archived-feature-qualification"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as target:
                while chunk := response.read(1024 * 1024):
                    target.write(chunk)
            attempt = {
                "commit": commit,
                "bytes": temporary.stat().st_size,
                "sha256": _sha256(temporary),
            }
            attempts.append(attempt)
            if _matches(temporary, record):
                temporary.replace(output)
                return {
                    "label": label,
                    "status": "recovered_from_nfldata_git_history",
                    "commit": commit,
                    "path": output.as_posix(),
                    "sha256": _sha256(output),
                    "bytes": output.stat().st_size,
                    "attempts_before_match": len(attempts) - 1,
                }
        finally:
            if temporary.exists():
                temporary.unlink()
    raise ValueError(
        f"Could not recover {label} schedule bytes from nfldata Git history. "
        f"Expected sha256={record.get('sha256')} bytes={record.get('bytes')}; "
        f"attempts={attempts}"
    )


def _schedule_context(frame: pd.DataFrame, seasons: set[int]) -> pd.DataFrame:
    if "season" not in frame:
        raise ValueError("schedule is missing season")
    available = [column for column in _SCHEDULE_CONTEXT_COLUMNS if column in frame.columns]
    required = {"season", "week", "away_team", "home_team"}
    missing = required - set(available)
    if missing:
        raise ValueError(f"schedule missing context columns: {sorted(missing)}")
    subset = frame.loc[pd.to_numeric(frame["season"], errors="coerce").isin(seasons), available].copy()
    for column in subset.columns:
        if column in {"season", "week"}:
            subset[column] = pd.to_numeric(subset[column], errors="coerce")
    sort_keys = [key for key in ("season", "week", "game_id", "away_team", "home_team") if key in subset]
    return subset.sort_values(sort_keys).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Qualify the preserved July 30 weekly feature artifact against the frozen benchmark "
            "source manifest and prove schedule-context equivalence on the historical seasons."
        )
    )
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument(
        "--benchmark-manifest",
        type=Path,
        default=Path("artifacts/reports/benchmark_real/DATA_MANIFEST.json"),
    )
    parser.add_argument("--seasons", nargs="+", type=int, default=[2020, 2021, 2022, 2023, 2024])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/archived_feature_panel_qualification"),
    )
    args = parser.parse_args()

    artifact_manifest_path = args.artifact_root / "artifacts/models/source_manifest.json"
    feature_panel_path = args.artifact_root / "data/processed/weekly_features_current.parquet"
    if not artifact_manifest_path.is_file() or not feature_panel_path.is_file():
        raise FileNotFoundError(
            "Preserved weekly-model artifact is incomplete; expected source_manifest.json and "
            "weekly_features_current.parquet"
        )

    benchmark = _load(args.benchmark_manifest)
    archived = _load(artifact_manifest_path)
    benchmark_records = _records(benchmark)
    archived_records = _records(archived)
    seasons = sorted(set(int(season) for season in args.seasons))

    player_checks: list[dict[str, object]] = []
    for season in seasons:
        name = f"player_stats_{season}"
        expected = benchmark_records.get(name)
        observed = archived_records.get(name)
        if expected is None or observed is None:
            raise ValueError(f"Missing player source provenance for {name}")
        matched = (
            str(expected.get("sha256")) == str(observed.get("sha256"))
            and int(expected.get("bytes", -1)) == int(observed.get("bytes", -2))
        )
        player_checks.append(
            {
                "name": name,
                "matched": matched,
                "benchmark_sha256": expected.get("sha256"),
                "archived_sha256": observed.get("sha256"),
                "benchmark_bytes": expected.get("bytes"),
                "archived_bytes": observed.get("bytes"),
            }
        )
        if not matched:
            raise ValueError(f"Archived feature panel player-source identity differs for {name}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    frozen_schedule = _recover_schedule(
        benchmark_records["schedules"],
        until=str(benchmark["created_at_utc"]),
        output=args.output_dir / "frozen_games.csv",
        label="frozen_benchmark",
    )
    archived_schedule = _recover_schedule(
        archived_records["schedules"],
        until=str(archived["created_at_utc"]),
        output=args.output_dir / "archived_feature_games.csv",
        label="archived_feature_panel",
    )

    frozen_context = _schedule_context(
        pd.read_csv(args.output_dir / "frozen_games.csv"), set(seasons)
    )
    archived_context = _schedule_context(
        pd.read_csv(args.output_dir / "archived_feature_games.csv"), set(seasons)
    )
    try:
        pd.testing.assert_frame_equal(
            frozen_context,
            archived_context,
            check_dtype=False,
            check_exact=True,
        )
        schedule_context_equivalent = True
        schedule_difference = None
    except AssertionError as exc:
        schedule_context_equivalent = False
        schedule_difference = str(exc)
    if not schedule_context_equivalent:
        raise ValueError(
            "Archived feature panel schedule context differs from the frozen benchmark on the "
            f"requested seasons: {schedule_difference}"
        )

    copied_feature_panel = args.output_dir / "weekly_features_current.parquet"
    shutil.copyfile(feature_panel_path, copied_feature_panel)
    audit = {
        "schema_version": 1,
        "authority": "research_evidence_only",
        "source_artifact": {
            "workflow_run_id": 30541589749,
            "artifact_id": 8759336388,
            "artifact_name": "weekly-model-review-30541589749",
            "artifact_digest_sha256": "197e7297d7e6c70669fc1101bddb624a4cc503c257317d4f1942b34cd7b2534e",
        },
        "archived_source_manifest": {
            "created_at_utc": archived.get("created_at_utc"),
            "path": artifact_manifest_path.as_posix(),
            "sha256": _sha256(artifact_manifest_path),
        },
        "benchmark_manifest": {
            "created_at_utc": benchmark.get("created_at_utc"),
            "path": args.benchmark_manifest.as_posix(),
            "sha256": _sha256(args.benchmark_manifest),
        },
        "seasons_compared": seasons,
        "player_source_identity_verified": True,
        "player_source_checks": player_checks,
        "frozen_schedule": frozen_schedule,
        "archived_schedule": archived_schedule,
        "schedule_context_columns": list(frozen_context.columns),
        "schedule_context_rows": int(len(frozen_context)),
        "schedule_context_equivalent": True,
        "feature_panel": {
            "path": copied_feature_panel.as_posix(),
            "bytes": copied_feature_panel.stat().st_size,
            "sha256": _sha256(copied_feature_panel),
        },
        "historical_production_parity_verified": False,
        "activation_review_permitted_from_this_provenance_alone": False,
        "interpretation": (
            "The preserved July 30 processed feature panel is backed by player-stat source hashes "
            "that match the frozen benchmark and schedule context proven equivalent over the "
            "requested historical seasons. The original raw player CSV bytes are not present in "
            "the retained artifact, so this provenance is sufficient for a research ablation but "
            "not for activation-review authority."
        ),
    }
    (args.output_dir / "qualification_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
