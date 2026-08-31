from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from player_state_engine.product.draft_day_doctor_adapter import is_real_league_summary
from player_state_engine.product.nfl_hub import load_nfl_hub_snapshot, refresh_nfl_hub
from player_state_engine.product.special_teams_refresh import refresh_special_teams_market

LaunchStageStatus = Literal["REFRESHED", "PRESERVED", "SKIPPED", "FAILED"]


@dataclass(frozen=True, slots=True)
class DraftLaunchStage:
    name: str
    status: LaunchStageStatus
    detail: str
    data: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class DraftLaunchReport:
    status: str
    can_open_war_room: bool
    authority: str
    champion_mutated: bool
    model_promotion_performed: bool
    stages: tuple[DraftLaunchStage, ...]
    doctor: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class DraftLaunchControlService:
    """Refresh mutable draft-day inputs, then re-run the authoritative Doctor.

    This service deliberately has no artifact-registry or promotion dependency. It cannot derive a
    production approval, move a champion pointer, retrain a model, or rewrite projection bytes.
    """

    def __init__(
        self,
        *,
        draft_service: Any,
        connection_service: Any,
        doctor_service: Any,
        nfl_hub_root: str | Path | None = None,
        nfl_hub_projections_path: str | Path | None = None,
        special_teams_path: str | Path | None = None,
    ) -> None:
        self.draft_service = draft_service
        self.connection_service = connection_service
        self.doctor_service = doctor_service
        self.nfl_hub_root = Path(
            nfl_hub_root or os.getenv("PSE_NFL_HUB_ROOT", "data/product/nfl_hub")
        )
        self.nfl_hub_projections_path = (
            str(nfl_hub_projections_path)
            if nfl_hub_projections_path is not None
            else os.getenv("PSE_NFL_HUB_PROJECTIONS_PATH", "")
        )
        self.special_teams_path = Path(
            special_teams_path
            or os.getenv(
                "PSE_SPECIAL_TEAMS_MARKET_PATH",
                "data/product/special_teams_market/current.json",
            )
        )
        self._lock = Lock()

    @staticmethod
    def _stage(
        name: str,
        status: LaunchStageStatus,
        detail: str,
        **data: object,
    ) -> DraftLaunchStage:
        return DraftLaunchStage(name=name, status=status, detail=detail, data=data or None)

    def _real_league_summaries(self) -> list[dict[str, object]]:
        return [
            dict(item)
            for item in self.draft_service.list_leagues()
            if is_real_league_summary(dict(item))
        ]

    def _refresh_hub(self, season: int) -> DraftLaunchStage:
        try:
            snapshot = refresh_nfl_hub(
                season=int(season),
                root=self.nfl_hub_root,
                projections_path=self.nfl_hub_projections_path,
            )
        except Exception as exc:  # noqa: BLE001 - preserve last good current-state snapshot.
            previous = load_nfl_hub_snapshot(self.nfl_hub_root)
            if previous is not None:
                return self._stage(
                    "nfl_hub",
                    "PRESERVED",
                    "NFL Hub refresh failed; preserved the previous snapshot for Doctor evaluation.",
                    error=str(exc),
                    previous_generated_at_utc=previous.get("generated_at_utc"),
                )
            return self._stage(
                "nfl_hub",
                "FAILED",
                "NFL Hub refresh failed and no previous snapshot is available.",
                error=str(exc),
            )
        return self._stage(
            "nfl_hub",
            "REFRESHED",
            "NFL observational state refreshed.",
            generated_at_utc=snapshot.get("generated_at_utc"),
            source_status=snapshot.get("status"),
            authority=snapshot.get("authority"),
        )

    def _refresh_adp(self, season: int) -> DraftLaunchStage:
        if not str(os.getenv("PSE_FANTASYPROS_API_KEY", "")).strip():
            status = dict(self.draft_service.market_status())
            return self._stage(
                "live_adp",
                "SKIPPED",
                "FantasyPros API key is not configured; preserved neutral/current cached timing semantics.",
                market_available=bool(status.get("available")),
                reason=status.get("reason"),
            )
        try:
            result = dict(self.draft_service.refresh_market(int(season)))
        except Exception as exc:  # noqa: BLE001 - external market failure must preserve prior state.
            status = dict(self.draft_service.market_status())
            if bool(status.get("available")):
                return self._stage(
                    "live_adp",
                    "PRESERVED",
                    "Live ADP refresh failed; preserved the previous integrity-checked market snapshot.",
                    error=str(exc),
                    age_seconds=status.get("age_seconds"),
                )
            return self._stage(
                "live_adp",
                "FAILED",
                "Live ADP refresh failed and no valid market snapshot is available; timing remains neutral.",
                error=str(exc),
            )
        return self._stage(
            "live_adp",
            "REFRESHED",
            "Point-in-time ADP timing overlay refreshed without modifying projection bytes.",
            rows=result.get("rows"),
            captured_at_utc=result.get("captured_at_utc"),
        )

    @staticmethod
    def _requires_special_teams(snapshots: list[Any]) -> bool:
        aliases = {"K", "PK", "DST", "DEF", "D/ST"}
        return any(
            str(slot).upper() in aliases
            for snapshot in snapshots
            for slot in snapshot.settings.roster_positions
        )

    def _refresh_special_teams(self, season: int, snapshots: list[Any]) -> DraftLaunchStage:
        if not self._requires_special_teams(snapshots):
            return self._stage(
                "special_teams_market",
                "SKIPPED",
                "No connected real league requires K/DST slots.",
            )
        try:
            result = refresh_special_teams_market(
                int(season),
                output=self.special_teams_path,
            )
        except Exception as exc:  # noqa: BLE001 - Doctor will validate any preserved snapshot.
            if self.special_teams_path.is_file():
                try:
                    previous = json.loads(self.special_teams_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    previous = None
                if isinstance(previous, dict):
                    return self._stage(
                        "special_teams_market",
                        "PRESERVED",
                        "K/DST market refresh failed; preserved the previous model-free market snapshot.",
                        error=str(exc),
                        previous_generated_at_utc=previous.get("generated_at_utc"),
                    )
            return self._stage(
                "special_teams_market",
                "FAILED",
                "K/DST market refresh failed and no prior snapshot can be evaluated.",
                error=str(exc),
            )
        return self._stage(
            "special_teams_market",
            "REFRESHED",
            "K/DST external-market-only guidance refreshed.",
            **result,
        )

    def _refresh_leagues(self) -> tuple[list[DraftLaunchStage], list[Any]]:
        stages: list[DraftLaunchStage] = []
        snapshots: list[Any] = []
        summaries = self._real_league_summaries()
        if not summaries:
            return [
                self._stage(
                    "real_leagues",
                    "SKIPPED",
                    "No connected real leagues are available to refresh.",
                )
            ], snapshots

        for summary in summaries:
            league_id = str(summary.get("league_id"))
            try:
                previous = self.draft_service.load_snapshot(league_id)
            except Exception as exc:  # noqa: BLE001
                stages.append(
                    self._stage(
                        f"league:{league_id}",
                        "FAILED",
                        "Connected league snapshot could not be loaded before refresh.",
                        error=str(exc),
                    )
                )
                continue
            platform = str(previous.identity.platform).lower()
            if platform not in {"sleeper", "espn"}:
                stages.append(
                    self._stage(
                        f"league:{league_id}",
                        "SKIPPED",
                        f"Live refresh is not supported for platform {platform}.",
                    )
                )
                snapshots.append(previous)
                continue
            try:
                result = self.connection_service.connect(
                    platform=platform,
                    league_id=league_id,
                    season=int(previous.identity.season),
                    external_user_id=previous.identity.external_user_id,
                    include_free_agents=True,
                )
                refreshed = self.draft_service.load_snapshot(league_id)
            except Exception as exc:  # noqa: BLE001 - previous validated snapshot stays authoritative.
                stages.append(
                    self._stage(
                        f"league:{league_id}",
                        "PRESERVED",
                        "Platform refresh failed; preserved the previous validated league snapshot.",
                        platform=platform,
                        league_name=previous.identity.name,
                        error=str(exc),
                    )
                )
                snapshots.append(previous)
                continue
            stages.append(
                self._stage(
                    f"league:{league_id}",
                    "REFRESHED",
                    "Real league rules, rosters, ownership, and draft state refreshed and revalidated.",
                    platform=platform,
                    league_name=result.league_name,
                    roster_count=result.roster_count,
                )
            )
            snapshots.append(refreshed)
        return stages, snapshots

    def status(self) -> dict[str, object]:
        doctor = self.doctor_service.report().as_dict()
        return {
            "status": doctor["status"],
            "can_open_war_room": doctor["can_open_war_room"],
            "authority": "current_state_refresh_only",
            "champion_mutated": False,
            "model_promotion_performed": False,
            "doctor": doctor,
        }

    def prepare(self, *, season: int = 2026) -> DraftLaunchReport:
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Draft preparation is already running in this API process.")
        try:
            stages: list[DraftLaunchStage] = []
            stages.append(self._refresh_hub(int(season)))
            league_stages, snapshots = self._refresh_leagues()
            stages.extend(league_stages)
            stages.append(self._refresh_special_teams(int(season), snapshots))
            stages.append(self._refresh_adp(int(season)))
            doctor = self.doctor_service.report()
            return DraftLaunchReport(
                status=doctor.status,
                can_open_war_room=doctor.can_open_war_room,
                authority="current_state_refresh_only",
                champion_mutated=False,
                model_promotion_performed=False,
                stages=tuple(stages),
                doctor=doctor.as_dict(),
            )
        finally:
            self._lock.release()
