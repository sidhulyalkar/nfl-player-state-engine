from __future__ import annotations

import argparse
from pathlib import Path

from player_state_engine.data.io import read_table, write_table
from player_state_engine.fantasy.decision_audit import (
    load_decision_records,
    settle_draft_decision_regret,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Settle live-draft decision receipts against a realized utility table."
    )
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=Path("artifacts/decision_audit/draft_decisions.jsonl"),
    )
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--player-id-column", default="player_id")
    parser.add_argument("--value-column", default="realized_value")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/reports/draft_decision_regret.csv"),
    )
    args = parser.parse_args()

    records = load_decision_records(args.audit_log)
    outcomes = read_table(args.outcomes)
    settled = settle_draft_decision_regret(
        records,
        outcomes,
        player_id_column=args.player_id_column,
        value_column=args.value_column,
    )
    output = write_table(settled, args.output)
    if settled.empty:
        print("No decision receipts were available to settle.")
    else:
        valid = settled["decision_regret"].dropna()
        mean_regret = float(valid.mean()) if len(valid) else float("nan")
        zero_regret = float((valid <= 1e-12).mean()) if len(valid) else float("nan")
        print(settled.to_string(index=False))
        print(f"\nSettled decisions: {len(valid)}/{len(settled)}")
        print(f"Mean visible-set regret: {mean_regret:.3f}")
        print(f"Zero-regret rate: {zero_regret:.1%}")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
