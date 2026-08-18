from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import write_table

LOGGER = logging.getLogger(__name__)


def _to_pandas(frame: object) -> pd.DataFrame:
    if isinstance(frame, pd.DataFrame):
        return frame
    if hasattr(frame, "to_pandas"):
        return frame.to_pandas()  # type: ignore[no-any-return]
    raise TypeError(f"Unsupported dataframe type: {type(frame)!r}")


def _load_player_stats(nfl: object, seasons: list[int]) -> object:
    loader = nfl.load_player_stats
    try:
        return loader(seasons, summary_level="week")
    except TypeError:
        return loader(seasons)


def _filter_seasons(frame: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    if "season" not in frame:
        return frame
    values = pd.to_numeric(frame["season"], errors="coerce")
    return frame.loc[values.isin(seasons)].copy()


def _download_optional_tables(
    loaders: dict[str, Callable[[], object]],
    output_dir: Path,
    paths: dict[str, Path],
    *,
    seasons: list[int] | None = None,
) -> None:
    for name, loader in loaders.items():
        try:
            LOGGER.info("Downloading optional/intelligence table %s", name)
            frame = _to_pandas(loader())
            if seasons:
                frame = _filter_seasons(frame, seasons)
            paths[name] = write_table(frame, output_dir / f"{name}.parquet")
        except Exception as exc:  # noqa: BLE001
            # These datasets are useful sensors, not a reason for the core player-state build to fail.
            LOGGER.warning("Skipping optional table %s: %s", name, exc)


def download_nflverse(
    seasons: Iterable[int],
    output_dir: str | Path,
    include_optional: bool = False,
    include_intelligence: bool = False,
) -> dict[str, Path]:
    """Download public nflverse tables using the maintained Python client.

    nflreadpy returns Polars frames; this boundary converts them to pandas and persists immutable
    raw Parquet files. ``include_intelligence`` adds fantasy IDs/rankings/opportunity and injuries
    as fail-soft evidence streams. A temporary source outage never silently deletes core stats.
    """

    try:
        import nflreadpy as nfl
    except ImportError as exc:
        raise RuntimeError(
            "nflreadpy is required for live downloads. Install the project with `pip install -e .`."
        ) from exc

    years = sorted(set(int(year) for year in seasons))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    core_loaders: dict[str, Callable[[], object]] = {
        "player_stats": lambda: _load_player_stats(nfl, years),
        "schedules": lambda: nfl.load_schedules(years),
        "players": lambda: nfl.load_players(),
        "rosters": lambda: nfl.load_rosters(years),
        "rosters_weekly": lambda: nfl.load_rosters_weekly(years),
        "depth_charts": lambda: nfl.load_depth_charts(years),
    }
    optional_loaders: dict[str, Callable[[], object]] = {
        "snap_counts": lambda: nfl.load_snap_counts(years),
        "participation": lambda: nfl.load_participation(years),
        "nextgen_passing": lambda: nfl.load_nextgen_stats(years, stat_type="passing"),
        "nextgen_rushing": lambda: nfl.load_nextgen_stats(years, stat_type="rushing"),
        "nextgen_receiving": lambda: nfl.load_nextgen_stats(years, stat_type="receiving"),
        "ftn_charting": lambda: nfl.load_ftn_charting(years),
    }
    intelligence_loaders: dict[str, Callable[[], object]] = {
        "injuries": lambda: nfl.load_injuries(years),
        "ff_playerids": lambda: nfl.load_ff_playerids(),
        "ff_rankings": lambda: nfl.load_ff_rankings(type="draft"),
        "ff_opportunity": lambda: nfl.load_ff_opportunity(years, stat_type="weekly"),
    }

    paths: dict[str, Path] = {}
    for name, loader in core_loaders.items():
        LOGGER.info("Downloading %s", name)
        frame = _to_pandas(loader())
        if name == "players":
            frame = _filter_seasons(frame, years)
        paths[name] = write_table(frame, output_dir / f"{name}.parquet")

    if include_optional:
        _download_optional_tables(optional_loaders, output_dir, paths, seasons=years)
    if include_intelligence:
        _download_optional_tables(intelligence_loaders, output_dir, paths, seasons=years)

    return paths
