"""Build an evidence-only Combine-to-rookie tracking linkage (no correlation claims)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.research.bdb27_nfl import rookie_linkage


def _load_manifest(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError("missing or symlinked research manifest")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("authority") != "RESEARCH_ONLY_NO_PROMOTION":
        raise ValueError("untrusted manifest authority")
    return data


def build(combine_dir: Path, nfl_dirs: list[Path], output_dir: Path, *, position: str = "DB") -> dict:
    combine_dir = combine_dir.resolve()
    nfl_dirs = [path.resolve() for path in nfl_dirs]
    output_dir = output_dir.resolve()
    if output_dir == combine_dir or output_dir in nfl_dirs:
        raise ValueError("do not overwrite source research directories")
    cm = _load_manifest(combine_dir / "qualification_manifest.json")
    if cm.get("coordinate_handedness") != "USER_DECLARED_NOT_VERIFIED":
        raise ValueError("unrecognized Combine orientation status")
    combined_hash = cm.get("sources", {}).get("players.csv", {}).get("sha256")
    if not combined_hash:
        raise ValueError("missing player-source digest")
    combine = pd.read_csv(combine_dir / "asymmetry_RESEARCH_ONLY.csv")
    if combine.empty:
        raise ValueError("no Combine profile entries to link")
    nfl_tables = []
    years_seen: set[int] = set()
    for root in nfl_dirs:
        matching = list(root.glob(f"nfl_*_{position}_manifest.json"))
        if len(matching) != 1:
            raise ValueError("one matching NFL season manifest required per directory")
        nm = _load_manifest(matching[0])
        year = int(matching[0].name.split("_")[1])
        if year in years_seen:
            raise ValueError("duplicate NFL rookie-year manifest")
        years_seen.add(year)
        if nm.get("source_files", {}).get("players.csv") != combined_hash:
            raise ValueError("player registry SHA mismatch across sources")
        if nm.get("handedness") != "USER_DECLARED_NOT_VERIFIED":
            raise ValueError("unrecognized NFL orientation status")
        data = pd.read_csv(root / f"nfl_{year}_{position}_profiles_RESEARCH_ONLY.csv")
        nfl_tables.append(data)
    if not nfl_tables:
        raise ValueError("at least one NFL season profile is required")
    nfl = pd.concat(nfl_tables, ignore_index=True)
    combined = rookie_linkage(combine, nfl)
    combined = combined.loc[combined.position.eq(position)].copy()
    if combined.empty:
        raise ValueError("selected position has no Combine profile coverage")
    summary = {
        "schema_version": 1, "authority": "RESEARCH_ONLY_NO_PROMOTION",
        "position": position, "rookie_year_files": sorted(years_seen),
        "combine_drill_player_rows": len(combined),
        "distinct_combine_players": int(combined.player_id.nunique()),
        "players_with_nfl_profiles": int(combined.loc[combined.nfl_status.ne("no_rookie_tracking"), "player_id"].nunique()),
        "paired_player_drill_rows": int(combined.link_status.eq("paired_estimate_not_yet_validation").sum()),
        "distinct_paired_players": int(combined.loc[combined.link_status.eq("paired_estimate_not_yet_validation"), "player_id"].nunique()),
        "sign_comparisons_validated": False,
        "pre_registered_outcome_validation_complete": False,
        "limitations": [
            "No independent source coordinate verification; cross-domain sign comparison not proven",
            "No observed side-of-field context without ball/play direction metadata",
            "Not an NFL performance prediction, scouting ranking, or awareness measure",
            "Linkage is descriptive; no outcome testing, statistical association or injury claims",
            "Avoid publishing player-level licensed derivatives",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_dir / "transfer_coverage_PRIVATE.csv", index=False)
    (output_dir / "transfer_summary.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combine-dir", type=Path, required=True)
    parser.add_argument("--nfl-dir", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--position", choices=("DB", "WR", "TE", "OL", "DL"), default="DB")
    args = parser.parse_args()
    print(json.dumps(build(args.combine_dir, args.nfl_dir, args.output_dir,
                           position=args.position), indent=2))


if __name__ == "__main__":
    main()
