from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from player_state_engine.integrations.espn import ESPNImporter
from player_state_engine.integrations.sleeper import SleeperImporter
from player_state_engine.product.schemas import LeagueSnapshot
from player_state_engine.product.store import LeagueSnapshotStore

LeaguePlatform = Literal["sleeper", "espn"]
DEFAULT_PORTFOLIO_PATH = Path("data/product/league_portfolio.json")


@dataclass(frozen=True, slots=True)
class LeagueConnectionResult:
    league_id: str
    league_name: str
    platform: str
    season: int
    teams: int
    roster_count: int
    roster_positions: tuple[str, ...]
    scoring_key_count: int
    external_roster_id: str | None
    snapshot_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "league_id": self.league_id,
            "league_name": self.league_name,
            "platform": self.platform,
            "season": self.season,
            "teams": self.teams,
            "roster_count": self.roster_count,
            "roster_positions": list(self.roster_positions),
            "scoring_key_count": self.scoring_key_count,
            "external_roster_id": self.external_roster_id,
            "snapshot_path": self.snapshot_path,
        }


class LeaguePortfolioExpectationStore:
    """Local-only declaration of how many real draft leagues the operator expects to connect."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(
            path
            or os.getenv("PSE_LEAGUE_PORTFOLIO_PATH", str(DEFAULT_PORTFOLIO_PATH))
        )

    def expected_count(self) -> int | None:
        if self.path.is_file():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                value = int(payload.get("expected_league_count"))
                return value if value > 0 else None
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                return None
        raw = str(os.getenv("PSE_EXPECTED_DRAFT_LEAGUE_COUNT", "")).strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if value > 0 else None

    def save_expected_count(self, expected_league_count: int) -> Path:
        value = int(expected_league_count)
        if value < 1 or value > 20:
            raise ValueError("expected_league_count must be between 1 and 20")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        next_path = self.path.with_suffix(self.path.suffix + ".next")
        payload = {"schema_version": 1, "expected_league_count": value}
        next_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        next_path.replace(self.path)
        return self.path


def validate_connected_snapshot(
    snapshot: LeagueSnapshot,
    *,
    platform: LeaguePlatform,
    league_id: str,
    season: int,
) -> None:
    if snapshot.identity.platform != platform:
        raise ValueError(
            f"imported platform mismatch: expected {platform}, got {snapshot.identity.platform}"
        )
    if snapshot.identity.league_id != str(league_id):
        raise ValueError(
            "imported league identity mismatch: "
            f"expected {league_id}, got {snapshot.identity.league_id}"
        )
    if int(snapshot.identity.season) != int(season):
        raise ValueError(
            f"imported season mismatch: expected {season}, got {snapshot.identity.season}"
        )
    if not snapshot.rosters:
        raise ValueError("imported league contains no rosters")
    if int(snapshot.settings.teams) < 2:
        raise ValueError("imported league reports fewer than two teams")
    if not snapshot.settings.roster_positions:
        raise ValueError("imported league does not expose roster positions")
    if not snapshot.settings.scoring:
        raise ValueError("imported league does not expose scoring settings")


class LeagueConnectionService:
    """Explicit local write boundary for connecting real Sleeper/ESPN leagues.

    Browser requests never carry ESPN cookies. Private ESPN authentication is resolved only from the
    server environment by ``ESPNImporter``. A snapshot is persisted only after the importer returns
    and the identity/settings/roster contract validates.
    """

    def __init__(
        self,
        *,
        store: LeagueSnapshotStore | None = None,
        sleeper: SleeperImporter | None = None,
        espn: ESPNImporter | None = None,
    ) -> None:
        self.store = store or LeagueSnapshotStore(
            os.getenv("PSE_LEAGUE_STORE", "data/product/leagues")
        )
        self.sleeper = sleeper or SleeperImporter()
        self.espn = espn or ESPNImporter()

    def connect(
        self,
        *,
        platform: LeaguePlatform,
        league_id: str,
        season: int,
        external_user_id: str | None = None,
        include_free_agents: bool = True,
    ) -> LeagueConnectionResult:
        normalized_id = str(league_id).strip()
        if not normalized_id or not normalized_id.isdigit():
            raise ValueError("league_id must be a numeric Sleeper or ESPN league identifier")
        if platform == "sleeper":
            snapshot = self.sleeper.import_league(
                normalized_id,
                external_user_id=(str(external_user_id).strip() if external_user_id else None),
                include_free_agents=include_free_agents,
                player_pool_limit=650 if include_free_agents else None,
            )
        elif platform == "espn":
            snapshot = self.espn.import_league(
                normalized_id,
                season=int(season),
                external_user_id=None,
                include_free_agents=include_free_agents,
                free_agent_limit=350,
            )
        else:  # pragma: no cover - route/schema constrains this; retained for direct callers.
            raise ValueError(f"unsupported league platform: {platform}")

        validate_connected_snapshot(
            snapshot,
            platform=platform,
            league_id=normalized_id,
            season=int(season),
        )
        path = self.store.save(snapshot)
        return LeagueConnectionResult(
            league_id=snapshot.identity.league_id,
            league_name=snapshot.identity.name,
            platform=snapshot.identity.platform,
            season=snapshot.identity.season,
            teams=snapshot.settings.teams,
            roster_count=len(snapshot.rosters),
            roster_positions=tuple(snapshot.settings.roster_positions),
            scoring_key_count=len(snapshot.settings.scoring),
            external_roster_id=(
                str(snapshot.metadata.get("external_roster_id"))
                if snapshot.metadata.get("external_roster_id") is not None
                else None
            ),
            snapshot_path=str(path),
        )
