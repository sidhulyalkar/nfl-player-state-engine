from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.data.io import read_table
from player_state_engine.product.shadow_season import (
    ShadowSeasonStore,
    build_shadow_settlement,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Settle one immutable live shadow checkpoint against realized weekly outcomes."
    )
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--actuals", type=Path, required=True)
    parser.add_argument("--actual-column", default="actual")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument(
        "--output-root", type=Path, default=Path("artifacts/shadow_season")
    )
    args = parser.parse_args()

    store = ShadowSeasonStore(args.output_root)
    snapshot = store.load_snapshot(args.snapshot_id)
    actuals = read_table(args.actuals)
    settlement = build_shadow_settlement(
        snapshot,
        actuals,
        settled_at=datetime.now(UTC),
        actual_column=args.actual_column,
        source_metadata={
            "path": str(args.actuals),
            "sha256": _sha256(args.actuals),
        },
        require_complete=not args.allow_partial,
    )
    created = store.save_settlement(settlement)
    print(
        json.dumps(
            {
                "created": created,
                "snapshot_id": settlement["snapshot_id"],
                "settlement_id": settlement["settlement_id"],
                "content_sha256": settlement["content_sha256"],
                "path": str(store.settlement_path(str(settlement["snapshot_id"]))),
                "complete": settlement["complete"],
                "settled_count": settlement["settled_count"],
                "metrics": settlement["metrics"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
