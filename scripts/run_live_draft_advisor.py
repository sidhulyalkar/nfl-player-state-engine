from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.draft import DraftState
from player_state_engine.fantasy.draft_advisor import build_reliable_live_draft_board
from player_state_engine.fantasy.league import LeagueConfig


def _ids(values: list[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    flattened: list[str] = []
    for value in values:
        flattened.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(dict.fromkeys(flattened))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a guarded league-specific live fantasy draft board."
    )
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument("--league", type=Path, required=True, help="LeagueConfig YAML file")
    parser.add_argument("--draft-slot", type=int, required=True)
    parser.add_argument("--current-pick", type=int, required=True)
    parser.add_argument("--rounds", type=int, required=True)
    parser.add_argument("--drafted", action="append", help="Drafted player id(s), repeat or comma-separate")
    parser.add_argument("--roster", action="append", help="Your roster player id(s), repeat or comma-separate")
    parser.add_argument("--linear", action="store_true", help="Use a linear rather than snake draft")
    parser.add_argument("--room-simulations", type=int, default=800)
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/reports/live_draft_board.csv"),
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("artifacts/reports/live_draft_board.json"),
    )
    args = parser.parse_args()

    projections = read_table(args.projections)
    league = LeagueConfig.from_yaml(args.league)
    state = DraftState(
        teams=league.teams,
        draft_slot=args.draft_slot,
        current_pick=args.current_pick,
        total_rounds=args.rounds,
        drafted_player_ids=_ids(args.drafted),
        roster_player_ids=_ids(args.roster),
        snake=not args.linear,
    )
    board = build_reliable_live_draft_board(
        projections,
        league,
        state,
        room_simulations=args.room_simulations,
        room_seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    write_table(board, args.output)

    display_columns = [
        column
        for column in (
            "live_rank",
            "room_rank",
            "player_name",
            "player_id",
            "position",
            "draft_action",
            "guarded_draft_action",
            "live_draft_score",
            "room_challenger_score",
            "survival_to_next_pick",
            "room_survival_to_next_pick",
            "room_position_wait_loss",
            "draft_reliability",
            "draft_reliability_score",
            "draft_reasons",
            "draft_reliability_reasons",
        )
        if column in board
    ]
    top = board.head(max(1, int(args.top)))[display_columns].copy()
    payload = {
        "league": str(args.league),
        "current_pick": state.current_pick,
        "next_pick": state.next_pick,
        "draft_slot": state.draft_slot,
        "room_simulations": int(args.room_simulations),
        "recommendations": top.to_dict(orient="records"),
    }
    args.json_output.write_text(json.dumps(payload, indent=2, default=str))
    print(top.to_string(index=False))
    print(f"\nWrote full board to {args.output}")
    print(f"Wrote top recommendations to {args.json_output}")


if __name__ == "__main__":
    main()
