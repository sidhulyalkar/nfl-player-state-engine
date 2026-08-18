from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from player_state_engine.fantasy.draft import build_live_draft_board, draft_state_from_snapshot
from player_state_engine.integrations.portfolio import league_config_from_snapshot
from player_state_engine.product.schemas import LeagueSnapshot


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a live, league-specific draft board.")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument("--draft-slot", type=int, required=True)
    parser.add_argument("--roster-id")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--total-rounds", type=int)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("artifacts/draft/live_board.csv"))
    args = parser.parse_args()

    snapshot = LeagueSnapshot.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
    config = league_config_from_snapshot(snapshot, profile=args.profile)
    state = draft_state_from_snapshot(
        snapshot,
        draft_slot=args.draft_slot,
        roster_id=args.roster_id,
        total_rounds=args.total_rounds,
    )
    projections = _read_table(args.projections)
    board = build_live_draft_board(projections, config, state)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    board.to_csv(args.output, index=False)
    columns = [
        "live_rank",
        "player_name",
        "position",
        "live_draft_score",
        "draft_action",
        "market_adp",
        "survival_to_next_pick",
        "roster_need_score",
        "vorp",
        "draft_reasons",
    ]
    print(board[[column for column in columns if column in board]].head(args.top).to_string(index=False))
    print(f"\nSaved full board to {args.output}")


if __name__ == "__main__":
    main()
