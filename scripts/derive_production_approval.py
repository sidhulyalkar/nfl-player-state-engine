from __future__ import annotations

import argparse
import json
from pathlib import Path

from player_state_engine.learning.approval_derivation import derive_production_approved_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Derive a production-approved immutable manifest over exact challenger bytes. "
            "This command does not move the champion pointer."
        )
    )
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--registry-root", type=Path, default=Path("artifacts/registry"))
    parser.add_argument("--challenger-bundle-id", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--note")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    production = derive_production_approved_bundle(
        args.registry_root,
        args.bundle_root,
        challenger_bundle_id=args.challenger_bundle_id,
        approved_by=args.approved_by,
        approval_note=args.note,
    )
    print(
        json.dumps(
            {
                "bundle_id": production.bundle_id,
                "authority": production.authority,
                "activation_eligible": production.activation_eligible,
                "target": production.target,
                "champion_pointer_moved": False,
                "next_step": (
                    "Explicitly run scripts/artifact_registry.py promote with this exact bundle ID "
                    "only after reviewing the release rehearsal and approval provenance."
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
