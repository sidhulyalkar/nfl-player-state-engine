from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.integrations.espn import ESPNImporter
from player_state_engine.integrations.sleeper import SleeperImporter
from player_state_engine.product.schemas import LeagueSnapshot

SLEEPER_SCORING_MAP = {
    "pass_yd": "passing_yards",
    "pass_td": "passing_tds",
    "pass_int": "interceptions",
    "rush_yd": "rushing_yards",
    "rush_td": "rushing_tds",
    "rec": "receptions",
    "rec_yd": "receiving_yards",
    "rec_td": "receiving_tds",
    "fum_lost": "fumbles_lost",
}

# espn-api exposes abbreviations from its SETTINGS_SCORING_FORMAT_MAP. Keep this mapping
# intentionally limited to statistics represented by the projection engine. Unsupported ESPN
# bonuses remain visible in snapshot metadata rather than being guessed into a generic weight.
ESPN_SCORING_MAP = {
    "PY": "passing_yards",
    "PTD": "passing_tds",
    "INT": "interceptions",
    "RY": "rushing_yards",
    "RTD": "rushing_tds",
    "REC": "receptions",
    "REY": "receiving_yards",
    "RETD": "receiving_tds",
    "FUML": "fumbles_lost",
    "PASSING YARDS": "passing_yards",
    "TD PASS": "passing_tds",
    "INTERCEPTIONS THROWN": "interceptions",
    "RUSHING YARDS": "rushing_yards",
    "RUSHING TD": "rushing_tds",
    "EACH RECEPTION": "receptions",
    "RECEIVING YARDS": "receiving_yards",
    "RECEIVING TD": "receiving_tds",
    "TOTAL FUMBLES LOST": "fumbles_lost",
}

SLOT_ALIASES = {
    "BN": "BENCH",
    "BE": "BENCH",
    "D/ST": "DEF",
    "DST": "DEF",
    "W/R/T": "FLEX",
    "WR/RB/TE": "FLEX",
    "RB/WR/TE": "FLEX",
    "Q/W/R/T": "SUPER_FLEX",
    "OP": "SUPER_FLEX",
    "SUPERFLEX": "SUPER_FLEX",
    "SUPER_FLEX": "SUPER_FLEX",
    "SF": "SUPER_FLEX",
}


@dataclass(slots=True)
class LeagueConnection:
    key: str
    platform: str
    league_id: str | None = None
    season: int = 2026
    username: str | None = None
    external_user_id: str | None = None
    profile: str | None = None
    enabled: bool = True
    espn_s2_env: str = "PSE_ESPN_S2"
    swid_env: str = "PSE_ESPN_SWID"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> LeagueConnection:
        return cls(**payload)


class LeaguePortfolio:
    """Configuration and sync boundary for every fantasy league the user plays in."""

    def __init__(
        self,
        connections: list[LeagueConnection],
        *,
        root: str | Path = "data/product/live_leagues",
    ) -> None:
        self.connections = connections
        self.root = Path(root)

    @classmethod
    def from_yaml(cls, path: str | Path) -> LeaguePortfolio:
        payload = yaml.safe_load(Path(path).read_text()) or {}
        default_season = int(payload.get("season", 2026))
        connections = []
        for row in payload.get("leagues", []):
            item = dict(row)
            item.setdefault("season", default_season)
            connections.append(LeagueConnection.from_dict(item))
        return cls(
            connections, root=payload.get("snapshot_root", "data/product/live_leagues")
        )

    def _save(self, snapshot: LeagueSnapshot, key: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        safe_key = "".join(
            character for character in key if character.isalnum() or character in "-_"
        )
        path = self.root / f"{safe_key}.json"
        path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        return path

    def sync(self, *, include_free_agents: bool = True) -> dict[str, Path]:
        sleeper = SleeperImporter()
        espn = ESPNImporter()
        paths: dict[str, Path] = {}
        for connection in self.connections:
            if not connection.enabled:
                continue
            platform = connection.platform.lower()
            if platform == "sleeper":
                if connection.league_id:
                    snapshot = sleeper.import_league(
                        connection.league_id,
                        external_user_id=connection.external_user_id,
                        include_free_agents=include_free_agents,
                    )
                    paths[connection.key] = self._save(snapshot, connection.key)
                    continue
                if not connection.username:
                    raise ValueError(
                        f"Sleeper connection {connection.key!r} needs league_id or username"
                    )
                snapshots = sleeper.import_user_leagues(
                    connection.username,
                    season=connection.season,
                    include_free_agents=include_free_agents,
                )
                for snapshot in snapshots:
                    discovered_key = f"{connection.key}__{snapshot.identity.league_id}"
                    paths[discovered_key] = self._save(snapshot, discovered_key)
                continue
            if platform == "espn":
                if not connection.league_id:
                    raise ValueError(f"ESPN connection {connection.key!r} requires league_id")
                snapshot = espn.import_league(
                    connection.league_id,
                    season=connection.season,
                    espn_s2_env=connection.espn_s2_env,
                    swid_env=connection.swid_env,
                    external_user_id=connection.external_user_id,
                    include_free_agents=include_free_agents,
                )
                paths[connection.key] = self._save(snapshot, connection.key)
                continue
            raise ValueError(f"Unsupported fantasy platform: {connection.platform}")
        return paths


def _roster_slot_counts(roster_positions: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw_slot in roster_positions:
        slot = SLOT_ALIASES.get(str(raw_slot).upper(), str(raw_slot).upper())
        if slot in {"IR", "RESERVE", "TAXI", "ER"}:
            continue
        counts[slot] = counts.get(slot, 0) + 1
    return counts


def _map_scoring(
    raw: dict[str, float], mapping: dict[str, str]
) -> tuple[dict[str, float], list[str]]:
    mapped: dict[str, float] = {}
    unsupported: list[str] = []
    for raw_name, value in raw.items():
        normalized = str(raw_name).strip().upper()
        target = mapping.get(raw_name) or mapping.get(normalized)
        if target:
            mapped[target] = float(value)
        elif abs(float(value)) > 1e-12:
            unsupported.append(str(raw_name))
    return mapped, sorted(set(unsupported))


def league_config_from_snapshot(
    snapshot: LeagueSnapshot,
    *,
    profile: str | Path | None = None,
) -> LeagueConfig:
    """Turn live platform settings into the same LeagueConfig used by the draft model."""
    base = (
        LeagueConfig.from_yaml(profile)
        if profile
        else LeagueConfig(teams=snapshot.settings.teams)
    )
    base.teams = snapshot.settings.teams

    live_slots = _roster_slot_counts(snapshot.settings.roster_positions)
    if live_slots:
        base.roster_slots = live_slots

    mapped_scoring: dict[str, float] = {}
    unsupported_scoring: list[str] = []
    reception: float | None = None
    if snapshot.identity.platform == "sleeper":
        mapped_scoring, unsupported_scoring = _map_scoring(
            snapshot.settings.scoring, SLEEPER_SCORING_MAP
        )
        raw_reception = snapshot.settings.scoring.get("rec")
        if raw_reception is not None:
            reception = float(raw_reception)
    elif snapshot.identity.platform == "espn":
        mapped_scoring, unsupported_scoring = _map_scoring(
            snapshot.settings.scoring, ESPN_SCORING_MAP
        )
        if "REC" in snapshot.settings.scoring:
            reception = float(snapshot.settings.scoring["REC"])
        elif "Each Reception" in snapshot.settings.scoring:
            reception = float(snapshot.settings.scoring["Each Reception"])

    if mapped_scoring:
        base.scoring_weights.update(mapped_scoring)
    if reception is not None:
        if abs(reception - 0.5) < 1e-9:
            base.scoring = "half_ppr"
        elif reception >= 0.95:
            base.scoring = "ppr"
        else:
            base.scoring = "standard"

    # Preserve unsupported live scoring rules in snapshot metadata so product provenance can
    # warn that component-level rescoring is incomplete instead of silently inventing values.
    if unsupported_scoring:
        snapshot.metadata["unsupported_scoring_keys"] = unsupported_scoring

    base.median_scoring = bool(snapshot.settings.median_scoring or base.median_scoring)
    if snapshot.settings.superflex and "SUPER_FLEX" not in base.roster_slots:
        base.roster_slots["SUPER_FLEX"] = 1
    if snapshot.settings.draft_type:
        base.draft_type = snapshot.settings.draft_type
    base.__post_init__()
    return base
