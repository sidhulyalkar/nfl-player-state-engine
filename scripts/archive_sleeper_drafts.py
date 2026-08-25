from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from player_state_engine.fantasy.draft_market_archive import archive_sleeper_draft
from player_state_engine.integrations.sleeper_drafts import SleeperDraftClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive completed historical Sleeper draft outcomes as immutable raw evidence."
    )
    parser.add_argument("--user", required=True, help="Sleeper username or numeric user ID")
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/external/drafts/sleeper"),
    )
    parser.add_argument(
        "--include-mocks",
        action="store_true",
        help=(
            "Archive completed drafts without a league_id. Mock rooms are excluded by default "
            "because their behavior may not transfer to real league drafts."
        ),
    )
    args = parser.parse_args()

    client = SleeperDraftClient()
    user = client.get_user(args.user)
    user_id = str(user.get("user_id") or args.user)
    retrieved_at = datetime.now(UTC)
    archived: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []

    for season in sorted(set(args.seasons)):
        for listed in client.list_user_drafts(user_id, season=int(season)):
            draft_id = str(listed.get("draft_id") or "")
            if not draft_id:
                skipped.append({"season": int(season), "reason": "missing_draft_id"})
                continue
            listed_status = str(listed.get("status") or "unknown")
            if listed_status != "complete":
                skipped.append(
                    {
                        "season": int(season),
                        "draft_id": draft_id,
                        "reason": f"status:{listed_status}",
                    }
                )
                continue

            draft = client.get_draft(draft_id)
            status = str(draft.get("status") or listed_status)
            if status != "complete":
                skipped.append(
                    {"season": int(season), "draft_id": draft_id, "reason": f"status:{status}"}
                )
                continue
            if draft.get("league_id") in {None, ""} and not args.include_mocks:
                skipped.append(
                    {"season": int(season), "draft_id": draft_id, "reason": "mock_or_unlinked"}
                )
                continue

            picks = client.get_draft_picks(draft_id)
            traded = client.get_draft_traded_picks(draft_id)
            manifest = archive_sleeper_draft(
                args.output_root,
                draft=draft,
                picks=picks,
                traded_picks=traded,
                retrieved_at=retrieved_at,
                source_urls={
                    "draft.json": client.source_url(f"draft/{draft_id}"),
                    "picks.json": client.source_url(f"draft/{draft_id}/picks"),
                    "traded_picks.json": client.source_url(f"draft/{draft_id}/traded_picks"),
                },
            )
            archived.append(
                {
                    "season": manifest.get("season"),
                    "draft_id": manifest.get("draft_id"),
                    "league_id": manifest.get("league_id"),
                    "status": manifest.get("status"),
                    "draft_type": manifest.get("draft_type"),
                    "draft_started_at": manifest.get("draft_started_at"),
                }
            )

    report = {
        "schema_version": 1,
        "authority": "raw_external_evidence",
        "platform": "sleeper",
        "user_id": user_id,
        "requested_seasons": sorted(set(args.seasons)),
        "retrieved_at": retrieved_at.isoformat(),
        "output_root": str(args.output_root),
        "completed_drafts_only": True,
        "include_mocks": bool(args.include_mocks),
        "archived_drafts": archived,
        "skipped_drafts": skipped,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
