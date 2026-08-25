from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

DRAFT_TIME_COLUMNS = (
    "draft_started_at",
    "draft_start",
    "draft_timestamp",
    "draft_date",
)
MARKET_TIME_COLUMNS = (
    "market_snapshot_at",
    "adp_snapshot_at",
    "market_captured_at",
    "adp_captured_at",
)


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _write(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".parquet", ".pq"}:
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def _slot_for_pick(pick: int, teams: int) -> int:
    round_number = (pick - 1) // teams + 1
    within_round = (pick - 1) % teams + 1
    return within_round if round_number % 2 == 1 else teams - within_round + 1


def _next_pick_for_slot(current_pick: int, teams: int, slot: int, max_pick: int) -> int | None:
    current_round = (current_pick - 1) // teams + 1
    for round_number in range(current_round, (max_pick - 1) // teams + 2):
        if round_number % 2 == 1:
            pick = (round_number - 1) * teams + slot
        else:
            pick = (round_number - 1) * teams + (teams - slot + 1)
        if current_pick < pick <= max_pick:
            return pick
    return None


def _coalesce_datetime_aliases(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    *,
    label: str,
) -> tuple[pd.Series, pd.Series]:
    """Resolve timestamp aliases row by row and refuse contradictory provenance."""

    values = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    sources = pd.Series(pd.NA, index=frame.index, dtype="string")
    conflict = pd.Series(False, index=frame.index, dtype=bool)

    for column in columns:
        if column not in frame:
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
        conflict |= values.notna() & parsed.notna() & (values != parsed)
        fill = values.isna() & parsed.notna()
        values.loc[fill] = parsed.loc[fill]
        sources.loc[fill] = column

    if bool(conflict.any()):
        identity_columns = [column for column in ("draft_id", "player_id") if column in frame]
        examples = frame.loc[conflict, identity_columns].head(5).to_dict("records")
        raise ValueError(
            f"Conflicting {label} timestamp aliases detected; refusing ambiguous provenance. "
            f"Examples: {examples}"
        )
    return values, sources


def _canonicalize_market_timestamps(data: pd.DataFrame) -> pd.DataFrame:
    output = data.copy()
    draft_time, draft_source = _coalesce_datetime_aliases(
        output,
        DRAFT_TIME_COLUMNS,
        label="draft-start",
    )
    market_time, market_source = _coalesce_datetime_aliases(
        output,
        MARKET_TIME_COLUMNS,
        label="market-snapshot",
    )
    output["draft_started_at"] = draft_time
    output["market_snapshot_at"] = market_time
    output["draft_timestamp_source"] = draft_source
    output["market_timestamp_source"] = market_source

    comparable = draft_time.notna() & market_time.notna()
    future_market = comparable & (market_time > draft_time)
    if bool(future_market.any()):
        examples = output.loc[
            future_market,
            [column for column in ("draft_id", "player_id") if column in output],
        ].head(5)
        raise ValueError(
            "Historical ADP snapshot was captured after its draft started; refusing market leakage. "
            f"Examples: {examples.to_dict('records')}"
        )

    derived_verified = comparable & (market_time <= draft_time)
    if "point_in_time_market_verified" in output:
        existing = output["point_in_time_market_verified"]
        if existing.dtype == bool:
            existing_verified = existing.fillna(False)
        else:
            existing_verified = existing.astype(str).str.lower().isin({"true", "1", "yes"})
        output["point_in_time_market_verified"] = existing_verified | derived_verified
    else:
        output["point_in_time_market_verified"] = derived_verified

    age = (draft_time - market_time).dt.total_seconds() / 3600.0
    output["market_snapshot_age_hours"] = age.where(comparable, np.nan)
    return output


def _round_for_pick(pick: int, teams: int) -> int:
    return (int(pick) - 1) // int(teams) + 1


def build_observations(
    drafts: pd.DataFrame,
    *,
    default_teams: int = 12,
    max_candidates_per_context: int = 80,
) -> pd.DataFrame:
    required = {"draft_id", "player_id", "actual_pick", "market_adp", "position"}
    missing = sorted(required - set(drafts.columns))
    if missing:
        raise ValueError(f"Historical draft table is missing required columns: {missing}")
    if int(default_teams) < 2:
        raise ValueError("default_teams must be at least 2")
    if int(max_candidates_per_context) < 1:
        raise ValueError("max_candidates_per_context must be positive")

    rows: list[dict[str, object]] = []
    for draft_id, group in drafts.groupby("draft_id", sort=False):
        data = _canonicalize_market_timestamps(group)
        data["actual_pick"] = pd.to_numeric(data["actual_pick"], errors="coerce")
        data["market_adp"] = pd.to_numeric(data["market_adp"], errors="coerce")
        if "market_adp_sd" in data:
            data["market_adp_sd"] = pd.to_numeric(data["market_adp_sd"], errors="coerce")
        data = data.dropna(subset=["actual_pick", "market_adp"]).sort_values("actual_pick")
        if data.empty:
            continue
        if bool((data["actual_pick"] < 1).any()):
            raise ValueError(f"Draft {draft_id!r} contains an actual_pick below 1")

        teams = int(default_teams)
        if "teams" in data:
            parsed_teams = pd.to_numeric(data["teams"], errors="coerce").dropna()
            if not parsed_teams.empty:
                teams = int(parsed_teams.iloc[0])
        teams = max(2, teams)
        max_pick = int(data["actual_pick"].max())

        for current_pick in range(1, max_pick + 1):
            slot = _slot_for_pick(current_pick, teams)
            next_pick = _next_pick_for_slot(current_pick, teams, slot, max_pick)
            if next_pick is None:
                continue
            recent_positions = (
                data.loc[data["actual_pick"] < current_pick]
                .tail(12)["position"]
                .astype(str)
                .str.upper()
            )
            run_counts = Counter(recent_positions)

            market_available = data.loc[data["actual_pick"] >= current_pick].copy()
            if market_available.empty:
                continue
            market_available["position"] = market_available["position"].astype(str).str.upper()
            market_available["position_market_rank"] = (
                market_available.groupby("position", sort=False)["market_adp"]
                .rank(method="first")
                .astype(int)
            )
            market_available["adp_distance_from_now"] = (
                market_available["market_adp"] - current_pick
            ).abs()
            market_depth = int(len(market_available))

            position_supply_to_next = (
                market_available.loc[market_available["market_adp"] < next_pick]
                .groupby("position", sort=False)
                .size()
                .to_dict()
            )
            position_supply_next_round = (
                market_available.loc[market_available["market_adp"] < next_pick + teams]
                .groupby("position", sort=False)
                .size()
                .to_dict()
            )

            available = market_available.sort_values(
                ["market_adp", "adp_distance_from_now", "player_id"],
                kind="mergesort",
            ).head(int(max_candidates_per_context))
            for _, candidate in available.iterrows():
                position = str(candidate["position"]).upper()
                record = candidate.to_dict()
                record.update(
                    {
                        "draft_id": str(draft_id),
                        "current_pick": current_pick,
                        "next_pick": next_pick,
                        "picks_until_next": int(next_pick - current_pick),
                        "current_round": _round_for_pick(current_pick, teams),
                        "next_pick_round": _round_for_pick(next_pick, teams),
                        "teams": teams,
                        "recent_position_run": int(run_counts.get(position, 0)),
                        "position_supply_to_next": int(position_supply_to_next.get(position, 0)),
                        "position_supply_next_round": int(
                            position_supply_next_round.get(position, 0)
                        ),
                        "draft_market_depth": market_depth,
                        "survived_to_next_pick": int(float(candidate["actual_pick"]) >= next_pick),
                    }
                )
                rows.append(record)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Expand historical drafts plus archived point-in-time ADP into survival observations."
        )
    )
    parser.add_argument("--drafts", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/draft_survival_observations.parquet"),
    )
    parser.add_argument("--default-teams", type=int, default=12)
    parser.add_argument("--max-candidates-per-context", type=int, default=80)
    args = parser.parse_args()
    observations = build_observations(
        _read(args.drafts),
        default_teams=args.default_teams,
        max_candidates_per_context=args.max_candidates_per_context,
    )
    _write(observations, args.output)
    verified = (
        float(observations["point_in_time_market_verified"].mean())
        if "point_in_time_market_verified" in observations and len(observations)
        else 0.0
    )
    print(
        f"Wrote {len(observations):,} survival observations to {args.output} "
        f"(point-in-time market verified: {verified:.1%})"
    )


if __name__ == "__main__":
    main()
