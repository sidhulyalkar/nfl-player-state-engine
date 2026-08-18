from __future__ import annotations

import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from player_state_engine.data.io import read_table
from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.draft import (
    DraftState,
    build_live_draft_board,
    draft_state_from_snapshot,
)
from player_state_engine.fantasy.draft_survival import (
    DraftSurvivalArtifact,
    apply_empirical_survival,
    load_survival_artifact,
)
from player_state_engine.fantasy.draft_survival import (
    artifact_metadata as survival_artifact_metadata,
)
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.roster_simulator import evaluate_candidate_impacts
from player_state_engine.integrations.espn import ESPNImporter
from player_state_engine.integrations.portfolio import league_config_from_snapshot
from player_state_engine.integrations.sleeper import SleeperImporter
from player_state_engine.product.provenance import frame_records, projection_metadata
from player_state_engine.product.schemas import LeagueSnapshot
from player_state_engine.product.store import LeagueSnapshotStore

try:
    from fastapi import FastAPI, HTTPException, Query
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


class DraftCompareRequest(BaseModel):
    roster_id: str
    player_ids: list[str] = Field(min_length=2, max_length=5)
    draft_slot: int | None = Field(default=None, ge=1)
    total_rounds: int | None = Field(default=None, ge=1)
    refresh: bool = False
    force_refresh: bool = False
    simulations: int = Field(default=600, ge=100, le=5000)


class DraftBoardService:
    """Authoritative server boundary for the live Draft War Room."""

    def __init__(
        self,
        *,
        store_root: str | Path | None = None,
        live_store_root: str | Path | None = None,
        projections_path: str | Path | None = None,
        survival_model_path: str | Path | None = None,
        refresh_seconds: float | None = None,
    ) -> None:
        self.store = LeagueSnapshotStore(
            store_root or os.getenv("PSE_LEAGUE_STORE", "data/product/leagues")
        )
        self.live_root = Path(
            live_store_root or os.getenv("PSE_LIVE_LEAGUE_STORE", "data/product/live_leagues")
        )
        self.projections_path = Path(
            projections_path
            or os.getenv(
                "PSE_PROJECTIONS_PATH", "artifacts/predictions/product_player_values.csv"
            )
        )
        self.survival_model_path = Path(
            survival_model_path
            or os.getenv(
                "PSE_DRAFT_SURVIVAL_MODEL",
                "artifacts/models/draft_survival/draft_survival.joblib",
            )
        )
        self.refresh_seconds = float(
            refresh_seconds
            if refresh_seconds is not None
            else os.getenv("PSE_DRAFT_REFRESH_SECONDS", "8")
        )
        self._last_refresh: dict[str, float] = {}
        self._sleeper = SleeperImporter()
        self._espn = ESPNImporter()
        self._survival_cache: tuple[float | None, DraftSurvivalArtifact | None] = (None, None)

    def _scan_live_store(self, league_id: str) -> LeagueSnapshot | None:
        if not self.live_root.exists():
            return None
        for path in self.live_root.glob("*.json"):
            try:
                snapshot = LeagueSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if snapshot.identity.league_id == str(league_id):
                return snapshot
        return None

    def load_snapshot(self, league_id: str) -> LeagueSnapshot:
        try:
            return self.store.load(league_id)
        except FileNotFoundError:
            snapshot = self._scan_live_store(league_id)
            if snapshot is None:
                raise
            return snapshot

    def list_leagues(self) -> list[dict[str, object]]:
        by_id = {str(item["league_id"]): item for item in self.store.list()}
        if self.live_root.exists():
            for path in sorted(self.live_root.glob("*.json")):
                try:
                    snapshot = LeagueSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                by_id.setdefault(
                    snapshot.identity.league_id,
                    {
                        "league_id": snapshot.identity.league_id,
                        "name": snapshot.identity.name,
                        "platform": snapshot.identity.platform,
                        "season": snapshot.identity.season,
                        "imported_at": snapshot.identity.imported_at.isoformat(),
                    },
                )
        output: list[dict[str, object]] = []
        for league_id, summary in by_id.items():
            try:
                snapshot = self.load_snapshot(league_id)
            except FileNotFoundError:
                output.append(summary)
                continue
            output.append(
                {
                    **summary,
                    "rosters": [
                        {"roster_id": roster.roster_id, "team_name": roster.team_name}
                        for roster in snapshot.rosters
                    ],
                    "external_roster_id": snapshot.metadata.get("external_roster_id"),
                    "draft_status": self._draft_status(snapshot),
                }
            )
        return sorted(output, key=lambda item: str(item.get("name") or item.get("league_id")))

    def _load_projections(self) -> pd.DataFrame:
        if not self.projections_path.exists():
            raise HTTPException(
                status_code=503, detail=f"Projection artifact unavailable: {self.projections_path}"
            )
        frame = read_table(self.projections_path)
        if frame.empty:
            raise HTTPException(status_code=503, detail="Projection artifact is empty.")
        return frame

    def _load_survival(self) -> DraftSurvivalArtifact | None:
        modified = (
            self.survival_model_path.stat().st_mtime if self.survival_model_path.exists() else None
        )
        if modified == self._survival_cache[0]:
            return self._survival_cache[1]
        artifact = load_survival_artifact(self.survival_model_path)
        self._survival_cache = (modified, artifact)
        return artifact

    def _refresh_snapshot(
        self, snapshot: LeagueSnapshot, *, force: bool
    ) -> tuple[LeagueSnapshot, str | None]:
        league_id = snapshot.identity.league_id
        now = time.monotonic()
        elapsed = now - self._last_refresh.get(league_id, -1e9)
        if not force and elapsed < self.refresh_seconds:
            return snapshot, None
        try:
            if snapshot.identity.platform == "sleeper":
                refreshed = self._sleeper.import_league(
                    league_id,
                    external_user_id=snapshot.identity.external_user_id,
                    include_free_agents=True,
                )
            elif snapshot.identity.platform == "espn":
                if not force and elapsed < max(self.refresh_seconds, 20.0):
                    return snapshot, None
                refreshed = self._espn.import_league(
                    league_id,
                    season=snapshot.identity.season,
                    external_user_id=snapshot.identity.external_user_id,
                    include_free_agents=True,
                )
            else:
                return snapshot, f"Live refresh is not implemented for {snapshot.identity.platform}."
            self.store.save(refreshed)
            self._last_refresh[league_id] = now
            return refreshed, None
        except Exception as exc:
            self._last_refresh[league_id] = now
            return snapshot, f"Platform refresh failed; preserved last valid snapshot: {exc}"

    @staticmethod
    def _draft_status(snapshot: LeagueSnapshot) -> str:
        active = snapshot.metadata.get("active_draft") or {}
        status = active.get("status") if isinstance(active, dict) else None
        if status:
            return str(status)
        return "drafting" if snapshot.metadata.get("live_draft_picks") else "pre_draft"

    @staticmethod
    def _pick_number(pick: dict[str, Any], fallback: int) -> int:
        for key in ("pick_no", "overall_pick", "pick", "pick_number"):
            value = pick.get(key)
            if value not in {None, ""}:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return fallback

    @staticmethod
    def _canonical_maps(
        snapshot: LeagueSnapshot,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        platform_to_canonical: dict[str, str] = {}
        details: dict[str, dict[str, Any]] = {}
        entries = [entry for roster in snapshot.rosters for entry in roster.players] + list(
            snapshot.free_agents
        )
        for entry in entries:
            platform_id = str(entry.platform_player_id)
            canonical = str(entry.canonical_player_id or platform_id)
            platform_to_canonical[platform_id] = canonical
            details[platform_id] = {
                "player_id": canonical,
                "platform_player_id": platform_id,
                "canonical_player_id": entry.canonical_player_id,
                "player_name": entry.player_name,
                "position": entry.position,
                "nfl_team": entry.nfl_team,
            }
        return platform_to_canonical, details

    def _normalized_picks(self, snapshot: LeagueSnapshot) -> list[dict[str, Any]]:
        raw = list(snapshot.metadata.get("live_draft_picks") or [])
        platform_to_canonical, details = self._canonical_maps(snapshot)
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(raw, start=1):
            pick = dict(item)
            raw_id = pick.get("platform_player_id") or pick.get("player_id")
            if raw_id not in {None, ""}:
                platform_id = str(raw_id)
                detail = details.get(platform_id, {})
                canonical = (
                    pick.get("canonical_player_id")
                    or platform_to_canonical.get(platform_id)
                    or pick.get("player_id")
                )
                pick["platform_player_id"] = platform_id
                pick["canonical_player_id"] = canonical if canonical != platform_id else None
                pick["player_id"] = str(canonical)
                for key in ("player_name", "position", "nfl_team"):
                    if not pick.get(key) and detail.get(key):
                        pick[key] = detail[key]
            pick["pick_no"] = self._pick_number(pick, index)
            normalized.append(pick)
        normalized.sort(key=lambda item: int(item.get("pick_no") or 0))
        return normalized

    def _resolve_draft_slot(
        self,
        snapshot: LeagueSnapshot,
        roster_id: str,
        requested: int | None,
        picks: list[dict[str, Any]],
    ) -> int:
        if requested is not None:
            return min(snapshot.settings.teams, max(1, int(requested)))
        active = snapshot.metadata.get("active_draft") or {}
        draft_order = active.get("draft_order") if isinstance(active, dict) else None
        if isinstance(draft_order, dict):
            manager_id = None
            try:
                manager_id = snapshot.roster(roster_id).manager_id
            except KeyError:
                pass
            for key in (snapshot.identity.external_user_id, manager_id):
                if key is not None and str(key) in draft_order:
                    return int(draft_order[str(key)])
        for pick in picks:
            pick_roster = pick.get("roster_id") or pick.get("team_id")
            if pick_roster is None or str(pick_roster) != str(roster_id):
                continue
            pick_no = int(pick.get("pick_no") or 0)
            if 1 <= pick_no <= snapshot.settings.teams:
                return pick_no
        raise HTTPException(
            status_code=422,
            detail={
                "code": "draft_slot_required",
                "message": "Draft slot could not be derived from the platform snapshot.",
            },
        )

    @staticmethod
    def _canonical_roster_ids(
        snapshot: LeagueSnapshot,
        roster_id: str,
        picks: list[dict[str, Any]],
    ) -> tuple[str, ...]:
        ids: list[str] = []
        try:
            roster = snapshot.roster(roster_id)
            ids.extend(
                str(entry.canonical_player_id or entry.platform_player_id)
                for entry in roster.players
            )
        except KeyError:
            pass
        for pick in picks:
            pick_roster = pick.get("roster_id") or pick.get("team_id")
            if (
                pick_roster is not None
                and str(pick_roster) == str(roster_id)
                and pick.get("player_id")
            ):
                ids.append(str(pick["player_id"]))
        return tuple(dict.fromkeys(ids))

    @staticmethod
    def _recent_runs(picks: list[dict[str, Any]], window: int = 12) -> dict[str, int]:
        positions = [str(pick.get("position") or "").upper() for pick in picks[-window:]]
        return dict(Counter(position for position in positions if position))

    @staticmethod
    def _format_label(config: LeagueConfig) -> str:
        qb = config.roster_slots.get("QB", 0)
        sf = sum(
            count
            for slot, count in config.flex_slots.items()
            if "QB" in config.flex_eligibility.get(slot, ())
        )
        qb_text = f"{qb}QB" if sf == 0 else f"{qb}QB+{sf}SF"
        scoring = str(config.scoring).replace("_", " ").title()
        median = " • Median" if config.median_scoring else ""
        return f"{config.teams}T • {qb_text} • {scoring}{median}"

    def _base_context(
        self,
        league_id: str,
        roster_id: str,
        *,
        draft_slot: int | None,
        total_rounds: int | None,
        refresh: bool,
        force_refresh: bool,
    ) -> tuple[
        LeagueSnapshot,
        pd.DataFrame,
        LeagueConfig,
        DraftState,
        list[dict[str, Any]],
        str | None,
    ]:
        snapshot = self.load_snapshot(league_id)
        refresh_warning = None
        if refresh or force_refresh:
            snapshot, refresh_warning = self._refresh_snapshot(snapshot, force=force_refresh)
        projections = self._load_projections()
        config = league_config_from_snapshot(snapshot)
        picks = self._normalized_picks(snapshot)
        slot = self._resolve_draft_slot(snapshot, roster_id, draft_slot, picks)
        state = draft_state_from_snapshot(
            snapshot, draft_slot=slot, roster_id=roster_id, total_rounds=total_rounds
        )
        drafted_ids = tuple(
            str(pick["player_id"]) for pick in picks if pick.get("player_id") not in {None, ""}
        )
        current_pick = max((int(pick.get("pick_no") or 0) for pick in picks), default=0) + 1
        state = DraftState(
            teams=state.teams,
            draft_slot=state.draft_slot,
            current_pick=current_pick,
            total_rounds=state.total_rounds,
            drafted_player_ids=drafted_ids,
            roster_player_ids=self._canonical_roster_ids(snapshot, roster_id, picks),
            snake=state.snake,
        )
        return snapshot, projections, config, state, picks, refresh_warning

    def _live_board(
        self,
        snapshot: LeagueSnapshot,
        projections: pd.DataFrame,
        config: LeagueConfig,
        state: DraftState,
        picks: list[dict[str, Any]],
    ) -> tuple[pd.DataFrame, DraftSurvivalArtifact | None, dict[str, int]]:
        board = build_live_draft_board(projections, config, state)
        run_counts = self._recent_runs(picks)
        survival = self._load_survival()
        board = apply_empirical_survival(
            board,
            survival,
            config,
            current_pick=state.current_pick,
            next_pick=state.next_pick,
            platform=snapshot.identity.platform,
            recent_position_runs=run_counts,
        )
        return board, survival, run_counts

    def board(
        self,
        league_id: str,
        roster_id: str,
        *,
        draft_slot: int | None = None,
        total_rounds: int | None = None,
        refresh: bool = True,
        force_refresh: bool = False,
        limit: int = 250,
    ) -> dict[str, object]:
        snapshot, projections, config, state, picks, refresh_warning = self._base_context(
            league_id,
            roster_id,
            draft_slot=draft_slot,
            total_rounds=total_rounds,
            refresh=refresh,
            force_refresh=force_refresh,
        )
        board, survival, run_counts = self._live_board(
            snapshot, projections, config, state, picks
        )
        trust = projection_metadata(projections, self.projections_path, snapshot=snapshot)
        roster_ids = set(state.roster_player_ids)
        full_board = build_decision_board(projections, config, DecisionType.DRAFT)
        roster = full_board.loc[full_board["player_id"].astype(str).isin(roster_ids)].copy()
        now = datetime.now(UTC)
        snapshot_age = max(0.0, (now - snapshot.identity.imported_at).total_seconds())
        projection_age = (
            max(0.0, now.timestamp() - self.projections_path.stat().st_mtime)
            if self.projections_path.exists()
            else None
        )
        stale_after = float(os.getenv("PSE_DRAFT_STALE_SECONDS", "60"))
        return {
            "league": {
                "league_id": snapshot.identity.league_id,
                "name": snapshot.identity.name,
                "platform": snapshot.identity.platform,
                "season": snapshot.identity.season,
                "format_label": self._format_label(config),
                "teams": config.teams,
                "roster_slots": dict(config.roster_slots),
                "scoring": config.scoring,
                "median_scoring": config.median_scoring,
            },
            "draft_state": {
                "status": self._draft_status(snapshot),
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
            "board": frame_records(board.head(max(1, min(int(limit), 1000)))),
            "trust": trust,
            "survival_model": survival_artifact_metadata(survival),
            "refresh_warning": refresh_warning,
            "snapshot_imported_at": snapshot.identity.imported_at.isoformat(),
            "snapshot_age_seconds": snapshot_age,
            "projection_age_seconds": projection_age,
            "stale_after_seconds": stale_after,
            "is_stale": snapshot_age > stale_after,
            "generated_at": now.isoformat(),
        }

    def compare(self, league_id: str, request: DraftCompareRequest) -> dict[str, object]:
        snapshot, projections, config, state, picks, refresh_warning = self._base_context(
            league_id,
            request.roster_id,
            draft_slot=request.draft_slot,
            total_rounds=request.total_rounds,
            refresh=request.refresh,
            force_refresh=request.force_refresh,
        )
        board, survival, _ = self._live_board(snapshot, projections, config, state, picks)
        requested = [str(player_id) for player_id in request.player_ids]
        candidate_rows = board.loc[board["player_id"].astype(str).isin(requested)].copy()
        found = set(candidate_rows["player_id"].astype(str))
        missing = [player_id for player_id in requested if player_id not in found]
        if missing:
            raise HTTPException(
                status_code=422,
                detail={"code": "players_unavailable", "player_ids": missing},
            )
        full_board = build_decision_board(projections, config, DecisionType.DRAFT)
        impacts = evaluate_candidate_impacts(
            full_board,
            config,
            state.roster_player_ids,
            requested,
            simulations=request.simulations,
        )
        impact_by_id = {impact.player_id: impact.to_dict() for impact in impacts}
        records = {str(row["player_id"]): row for row in frame_records(candidate_rows)}
        candidates: list[dict[str, object]] = []
        for player_id in requested:
            row = dict(records[player_id])
            row["roster_impact"] = impact_by_id.get(player_id)
            candidates.append(row)

        def winner(field: str, *, nested: bool = False) -> str | None:
            best_id = None
            best_value = -float("inf")
            for item in candidates:
                source = item.get("roster_impact") if nested else item
                if not isinstance(source, dict):
                    continue
                try:
                    value = float(source.get(field))
                except (TypeError, ValueError):
                    continue
                if value > best_value:
                    best_value = value
                    best_id = str(item["player_id"])
            return best_id

        q50_name = next(
            (
                column
                for column in (
                    "season_points_q50",
                    "fantasy_points_ppr_q50",
                    "decision_specific_score",
                )
                if column in candidate_rows
            ),
            "live_draft_score",
        )
        return {
            "league_id": league_id,
            "roster_id": request.roster_id,
            "draft_state": {
                "status": self._draft_status(snapshot),
                "draft_slot": state.draft_slot,
                "current_pick": state.current_pick,
                "next_pick": state.next_pick,
            },
            "candidates": candidates,
            "winners": {
                "best_raw_projection": winner(q50_name),
                "best_league_value": winner("vorp"),
                "best_roster_fit": winner("roster_fit_score", nested=True),
                "best_pick_now": winner("live_draft_score"),
            },
            "survival_model": survival_artifact_metadata(survival),
            "refresh_warning": refresh_warning,
            "generated_at": datetime.now(UTC).isoformat(),
        }


def install_draft_routes(
    app: FastAPI,
    *,
    store_root: str | Path | None = None,
    projections_path: str | Path | None = None,
) -> DraftBoardService:
    service = DraftBoardService(store_root=store_root, projections_path=projections_path)

    @app.get("/v1/draft/leagues")
    def draft_leagues() -> list[dict[str, object]]:
        return service.list_leagues()

    @app.get("/v1/leagues/{league_id}/draft/board")
    def live_draft_board(
        league_id: str,
        roster_id: str = Query(...),
        draft_slot: int | None = Query(default=None, ge=1),
        total_rounds: int | None = Query(default=None, ge=1),
        refresh: bool = True,
        force_refresh: bool = False,
        limit: int = Query(default=250, ge=1, le=1000),
    ) -> dict[str, object]:
        try:
            return service.board(
                league_id,
                roster_id,
                draft_slot=draft_slot,
                total_rounds=total_rounds,
                refresh=refresh,
                force_refresh=force_refresh,
                limit=limit,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/leagues/{league_id}/draft/compare")
    def compare_draft_candidates(
        league_id: str, request: DraftCompareRequest
    ) -> dict[str, object]:
        try:
            return service.compare(league_id, request)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return service
