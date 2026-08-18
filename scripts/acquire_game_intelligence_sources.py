from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.data.io import write_table
from player_state_engine.game_intelligence.sources import game_evidence_catalog


def _to_pandas(frame: object):
    if hasattr(frame, "to_pandas"):
        return frame.to_pandas()
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Acquire point-in-time and retrospective evidence for the v0.10 game engine."
    )
    parser.add_argument("--season", type=int, action="append", required=True)
    parser.add_argument("--output-dir", default="data/raw/game_intelligence")
    parser.add_argument("--include-retrospective", action="store_true")
    args = parser.parse_args()

    import nflreadpy as nfl

    seasons = sorted(set(args.season))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    captured = datetime.now(UTC).isoformat()
    paths: dict[str, str] = {}
    failures: dict[str, str] = {}

    required = {
        "play_by_play": lambda: nfl.load_pbp(seasons),
        "schedules": lambda: nfl.load_schedules(seasons),
    }
    fail_soft = {
        "players": lambda: nfl.load_players(),
        "rosters_weekly": lambda: nfl.load_rosters_weekly(seasons),
        "depth_charts": lambda: nfl.load_depth_charts(seasons),
        "snap_counts": lambda: nfl.load_snap_counts(seasons),
        "ftn_charting": lambda: nfl.load_ftn_charting(seasons),
        "nextgen_passing": lambda: nfl.load_nextgen_stats(seasons, stat_type="passing"),
        "nextgen_rushing": lambda: nfl.load_nextgen_stats(seasons, stat_type="rushing"),
        "nextgen_receiving": lambda: nfl.load_nextgen_stats(seasons, stat_type="receiving"),
        "officials": lambda: nfl.load_officials(seasons),
    }
    if args.include_retrospective:
        fail_soft["participation"] = lambda: nfl.load_participation(seasons)

    for name, loader in required.items():
        frame = _to_pandas(loader())
        path = write_table(frame, output_dir / f"{name}.parquet")
        paths[name] = str(path)

    for name, loader in fail_soft.items():
        try:
            frame = _to_pandas(loader())
            path = write_table(frame, output_dir / f"{name}.parquet")
            paths[name] = str(path)
        except Exception as exc:  # noqa: BLE001
            failures[name] = str(exc)

    manifest = {
        "captured_at_utc": captured,
        "seasons": seasons,
        "paths": paths,
        "failures": failures,
        "include_retrospective": bool(args.include_retrospective),
        "evidence_catalog": game_evidence_catalog(),
        "warning": (
            "Retrospective participation data must never be injected into a historical weekly "
            "prediction unless it was genuinely available before that prediction cutoff."
        ),
    }
    manifest_path = output_dir / "acquisition_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
