from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd


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
    rows: list[dict[str, object]] = []
    for draft_id, group in drafts.groupby("draft_id", sort=False):
        data = group.copy()
        data["actual_pick"] = pd.to_numeric(data["actual_pick"], errors="coerce")
        data["market_adp"] = pd.to_numeric(data["market_adp"], errors="coerce")
        data = data.dropna(subset=["actual_pick", "market_adp"]).sort_values("actual_pick")
        if data.empty:
            continue
        teams = default_teams
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
            available = data.loc[data["actual_pick"] >= current_pick].copy()
            # Best-market players plus notable fallers are the realistic decision set while
            # a manager is on the clock. Using final outcomes here would leak football value.
            available["adp_distance_from_now"] = (available["market_adp"] - current_pick).abs()
            available = available.sort_values(
                ["market_adp", "adp_distance_from_now"]
            ).head(max_candidates_per_context)
            for _, candidate in available.iterrows():
                position = str(candidate["position"]).upper()
                record = candidate.to_dict()
                record.update(
                    {
                        "draft_id": str(draft_id),
                        "current_pick": current_pick,
                        "next_pick": next_pick,
                        "teams": teams,
                        "recent_position_run": int(run_counts.get(position, 0)),
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
    print(f"Wrote {len(observations):,} survival observations to {args.output}")


if __name__ == "__main__":
    main()
