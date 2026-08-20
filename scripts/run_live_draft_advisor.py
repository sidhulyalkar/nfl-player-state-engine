from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.decision_audit import (
    append_decision_record,
    build_draft_audit_record,
)
from player_state_engine.fantasy.draft import DraftState
from player_state_engine.fantasy.draft_advisor import build_reliable_live_draft_board
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness


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
    parser.add_argument("--league-key", help="Stable league identifier used in the audit ledger")
    parser.add_argument("--draft-slot", type=int, required=True)
    parser.add_argument("--current-pick", type=int, required=True)
    parser.add_argument("--rounds", type=int, required=True)
    parser.add_argument(
        "--drafted",
        action="append",
        help="Drafted player id(s), repeat or comma-separate",
    )
    parser.add_argument(
        "--roster",
        action="append",
        help="Your roster player id(s), repeat or comma-separate",
    )
    parser.add_argument("--linear", action="store_true", help="Use a linear rather than snake draft")
    parser.add_argument("--room-simulations", type=int, default=800)
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument(
        "--strict-readiness",
        action="store_true",
        help="Stop when the projection pool cannot fully represent the league contract",
    )
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
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=Path("artifacts/decision_audit/draft_decisions.jsonl"),
    )
    args = parser.parse_args()

    projections = read_table(args.projections)
    league = LeagueConfig.from_yaml(args.league)
    readiness = assess_league_readiness(projections, league)
    if args.strict_readiness and not readiness.ready:
        print(json.dumps({"readiness": readiness.as_dict()}, indent=2, default=str))
        raise SystemExit(2)

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
    league_key = str(args.league_key or args.league.stem)
    audit_record = build_draft_audit_record(
        board,
        state,
        league,
        league_key=league_key,
        top_n=max(5, min(int(args.top), 25)),
        model_metadata={
            "room_challenger_promoted": False,
            "room_simulations": int(args.room_simulations),
            "room_seed": int(args.seed),
            "projection_artifact": str(args.projections),
        },
    )
    audit_appended = append_decision_record(args.audit_log, audit_record)

    payload = {
        "league": str(args.league),
        "league_key": league_key,
        "current_pick": state.current_pick,
        "next_pick": state.next_pick,
        "draft_slot": state.draft_slot,
        "room_simulations": int(args.room_simulations),
        "readiness": readiness.as_dict(),
        "decision_id": audit_record.decision_id,
        "audit_record_appended": audit_appended,
        "audit_log": str(args.audit_log),
        "recommendations": top.to_dict(orient="records"),
    }
    args.json_output.write_text(json.dumps(payload, indent=2, default=str))
    print(f"League readiness: {readiness.score:.1f}/100 • ready={readiness.ready}")
    if readiness.flags:
        print("Readiness flags: " + ", ".join(readiness.flags))
    print(top.to_string(index=False))
    print(f"\nDecision receipt: {audit_record.decision_id} ({'new' if audit_appended else 'existing'})")
    print(f"Wrote full board to {args.output}")
    print(f"Wrote top recommendations to {args.json_output}")
    print(f"Audit ledger: {args.audit_log}")


if __name__ == "__main__":
    main()
