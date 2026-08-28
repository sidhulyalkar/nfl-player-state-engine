from __future__ import annotations

import os
import time
from datetime import UTC, datetime

from player_state_engine.api.draft_routes import DraftBoardService
from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.draft_advisor import augment_live_draft_board_with_reliability
from player_state_engine.fantasy.draft_qualification import qualify_live_draft
from player_state_engine.fantasy.draft_survival import (
    artifact_metadata as survival_artifact_metadata,
)
from player_state_engine.fantasy.readiness import assess_league_readiness
from player_state_engine.product.provenance import frame_records, projection_metadata

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


def install_draft_reliability_routes(app: FastAPI, draft_service: DraftBoardService) -> None:
    """Install an additive reliability surface around the authoritative draft board."""

    @app.get("/v1/leagues/{league_id}/draft/reliable-board")
    def reliable_draft_board(
        league_id: str,
        roster_id: str = Query(...),
        draft_slot: int | None = Query(default=None, ge=1),
        total_rounds: int | None = Query(default=None, ge=1),
        refresh: bool = True,
        force_refresh: bool = False,
        limit: int = Query(default=250, ge=1, le=1000),
        room_simulations: int = Query(default=600, ge=100, le=5000),
        max_projection_age_hours: float = Query(default=24.0, gt=0.0, le=720.0),
    ) -> dict[str, object]:
        try:
            snapshot, projections, config, state, picks, refresh_warning = (
                draft_service._base_context(  # noqa: SLF001 - companion route by design
                    league_id,
                    roster_id,
                    draft_slot=draft_slot,
                    total_rounds=total_rounds,
                    refresh=refresh,
                    force_refresh=force_refresh,
                )
            )
            baseline, survival, run_counts = draft_service._live_board(  # noqa: SLF001
                snapshot, projections, config, state, picks
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if draft_service.projections_path.exists():
            projection_age_hours = max(
                0.0,
                (time.time() - draft_service.projections_path.stat().st_mtime) / 3600.0,
            )
        else:
            projection_age_hours = None

        reliable = augment_live_draft_board_with_reliability(
            baseline,
            projections,
            config,
            state,
            room_simulations=room_simulations,
            room_seed=state.current_pick * 1009 + state.draft_slot,
            projection_age_hours=projection_age_hours,
            max_projection_age_hours=max_projection_age_hours,
        )
        readiness = assess_league_readiness(projections, config)
        trust = projection_metadata(
            projections,
            draft_service.projections_path,
            snapshot=snapshot,
        )
        roster_ids = {str(player_id) for player_id in state.roster_player_ids}
        full_board = build_decision_board(projections, config, DecisionType.DRAFT)
        roster = full_board.loc[full_board["player_id"].astype(str).isin(roster_ids)].copy()

        now = datetime.now(UTC)
        stale_after = float(os.getenv("PSE_DRAFT_STALE_SECONDS", "60"))
        snapshot_age = max(0.0, (now - snapshot.identity.imported_at).total_seconds())
        qualification = qualify_live_draft(
            readiness,
            projection_age_hours=projection_age_hours,
            max_projection_age_hours=max_projection_age_hours,
            snapshot_age_seconds=snapshot_age,
            stale_after_seconds=stale_after,
            refresh_warning=refresh_warning,
        )

        return {
            "league": {
                "league_id": snapshot.identity.league_id,
                "name": snapshot.identity.name,
                "platform": snapshot.identity.platform,
                "season": snapshot.identity.season,
                "format_label": draft_service._format_label(config),  # noqa: SLF001
                "teams": config.teams,
                "roster_slots": dict(config.roster_slots),
                "scoring": config.scoring,
                "median_scoring": config.median_scoring,
            },
            "draft_state": {
                "status": draft_service._draft_status(snapshot),  # noqa: SLF001
                "draft_slot": state.draft_slot,
                "current_pick": state.current_pick,
                "next_pick": state.next_pick,
                "total_rounds": state.total_rounds,
                "completed_picks": len(picks),
                "recent_position_runs": run_counts,
            },
            "roster_id": roster_id,
            "roster": frame_records(roster),
            "recent_picks": picks[-16:],
            "board": frame_records(reliable.head(max(1, min(int(limit), 1000)))),
            "readiness": readiness.as_dict(),
            "qualification": qualification.as_dict(),
            "trust": trust,
            "survival_model": survival_artifact_metadata(survival),
            "research": {
                "room_challenger_promoted": False,
                "room_simulations": int(room_simulations),
                "baseline_survival_authoritative": True,
                "purpose": "structural_challenger_and_disagreement_sensor",
            },
            "projection_age_seconds": (
                None if projection_age_hours is None else projection_age_hours * 3600.0
            ),
            "max_projection_age_hours": float(max_projection_age_hours),
            "refresh_warning": refresh_warning,
            "snapshot_imported_at": snapshot.identity.imported_at.isoformat(),
            "snapshot_age_seconds": snapshot_age,
            "stale_after_seconds": stale_after,
            "is_stale": not qualification.live_snapshot_fresh,
            "generated_at": now.isoformat(),
        }
