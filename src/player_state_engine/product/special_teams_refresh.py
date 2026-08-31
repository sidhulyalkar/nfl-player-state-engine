from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from player_state_engine.product.nfl_hub import _to_pandas
from player_state_engine.product.special_teams_market import build_special_teams_market

DEFAULT_SPECIAL_TEAMS_PATH = Path("data/product/special_teams_market/current.json")


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".next",
            delete=False,
        ) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink(missing_ok=True)


def refresh_special_teams_market(
    season: int,
    *,
    output: str | Path | None = None,
) -> dict[str, object]:
    """Refresh model-free K/DST market guidance while preserving its authority boundary."""

    try:
        import nflreadpy as nfl
    except ImportError as exc:  # pragma: no cover - base runtime normally includes nflreadpy.
        raise RuntimeError("nflreadpy is required for special-teams market refresh") from exc

    rankings = _to_pandas(nfl.load_ff_rankings(type="draft"))
    playerids = _to_pandas(nfl.load_ff_playerids())
    rosters = _to_pandas(nfl.load_rosters([int(season)]))
    snapshot = build_special_teams_market(
        rankings,
        playerids,
        rosters,
        season=int(season),
    )
    if int(snapshot.get("kicker_count", 0)) <= 0:
        raise RuntimeError("No current kicker market entries resolved to current roster identities")
    if int(snapshot.get("dst_count", 0)) <= 0:
        raise RuntimeError("No current DST redraft market entries were available")
    if snapshot.get("authority") != "external_market_only":
        raise RuntimeError("Special-teams refresh produced unexpected authority")
    if snapshot.get("model_fields_present") is not False:
        raise RuntimeError("Special-teams market artifact must remain model-free")

    destination = Path(
        output
        or os.getenv(
            "PSE_SPECIAL_TEAMS_MARKET_PATH",
            str(DEFAULT_SPECIAL_TEAMS_PATH),
        )
    )
    _atomic_json(destination, snapshot)
    return {
        "output": str(destination),
        "authority": snapshot["authority"],
        "source_date": snapshot.get("source_date"),
        "kicker_count": snapshot["kicker_count"],
        "dst_count": snapshot["dst_count"],
        "generated_at_utc": snapshot.get("generated_at_utc"),
    }
