from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from player_state_engine.product.nfl_hub import _to_pandas
from player_state_engine.product.special_teams_market import build_special_teams_market


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh external-market-only kicker and DST redraft guidance from maintained "
            "ffverse/nflverse sources. No model projections or VORP are created."
        )
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/product/special_teams_market/current.json"),
    )
    args = parser.parse_args()

    try:
        import nflreadpy as nfl
    except ImportError as exc:
        raise RuntimeError("nflreadpy is required for special-teams market refresh") from exc

    rankings = _to_pandas(nfl.load_ff_rankings(type="draft"))
    playerids = _to_pandas(nfl.load_ff_playerids())
    rosters = _to_pandas(nfl.load_rosters([int(args.season)]))
    snapshot = build_special_teams_market(
        rankings,
        playerids,
        rosters,
        season=int(args.season),
    )
    if int(snapshot.get("kicker_count", 0)) <= 0:
        raise RuntimeError("No current kicker market entries resolved to current roster identities")
    if int(snapshot.get("dst_count", 0)) <= 0:
        raise RuntimeError("No current DST redraft market entries were available")
    if snapshot.get("authority") != "external_market_only":
        raise RuntimeError("Special-teams refresh produced unexpected authority")
    if snapshot.get("model_fields_present") is not False:
        raise RuntimeError("Special-teams market artifact must remain model-free")

    _atomic_json(args.output, snapshot)
    print(json.dumps({
        "output": str(args.output),
        "authority": snapshot["authority"],
        "source_date": snapshot.get("source_date"),
        "kicker_count": snapshot["kicker_count"],
        "dst_count": snapshot["dst_count"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
